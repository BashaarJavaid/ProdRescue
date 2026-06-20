"""Harness MCP server.

Wraps all Docker logic behind named tools so the QA agent never touches Docker
directly. Core functions are transport-agnostic (callable in tests); the FastMCP
wrapper is built lazily in ``build_server()`` / ``main()``.

Lifecycle per incident:
    spin_up_stack  → copy target, compose up, measure baseline coverage
    apply_patch    → write conftest + git-apply the diff to the mounted source
    run_pytest     → exec pytest+coverage in the app container, compute delta
    teardown_stack → compose down -v, force-remove leftovers, delete stack dir
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from services.config import settings
from services.mcp_servers.harness.compose import build_compose_config
from services.schemas.models import HarnessSpec

HARNESS_ROOT = Path("/tmp/harness")
ACTIVE_STACKS: dict[str, dict] = {}


async def _run(cmd: list[str], cwd: str | None = None, timeout: float = 600) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        # Kill the abandoned `docker compose exec` client so it doesn't linger;
        # teardown's `compose down` then removes the container running pytest.
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def _compose(stack: dict) -> list[str]:
    return ["docker", "compose", "-f", str(Path(stack["dir"]) / "docker-compose.yml")]


async def _coverage_percent(stack: dict) -> float:
    """Run coverage in the app container and return total percent covered.

    Used both for the baseline (pre-patch) and the post-patch measurement.
    """
    compose = _compose(stack)
    await _run(
        compose + ["exec", "-T", "app", "sh", "-lc",
                   "pytest --cov=src --cov-report=json:coverage.json -q || true"],
        timeout=300,
    )
    rc, out, _ = await _run(compose + ["exec", "-T", "app", "cat", "coverage.json"], timeout=30)
    if rc != 0:
        return 0.0
    try:
        return float(json.loads(out)["totals"]["percent_covered"])
    except (ValueError, KeyError):
        return 0.0


async def spin_up_stack(spec: dict) -> dict:
    harness_spec = HarnessSpec(**spec)
    stack_id = uuid.uuid4().hex[:12]
    stack_dir = HARNESS_ROOT / stack_id
    HARNESS_ROOT.mkdir(parents=True, exist_ok=True)

    # Copy the target repo into an isolated per-stack working dir.
    shutil.copytree(settings.target_repo_dir, stack_dir)

    compose_cfg = build_compose_config(harness_spec, stack_id)
    (stack_dir / "docker-compose.yml").write_text(yaml.safe_dump(compose_cfg, sort_keys=False))

    stack = {"dir": str(stack_dir), "spec": spec, "baseline_cov": 0.0}
    compose = _compose(stack)
    await _run(compose + ["build"], timeout=600)
    await _run(compose + ["up", "-d"], timeout=300)

    stack["baseline_cov"] = await _coverage_percent(stack)
    ACTIVE_STACKS[stack_id] = stack
    return {"stack_id": stack_id, "baseline_cov": stack["baseline_cov"]}


async def apply_patch(
    stack_id: str,
    patch_diff: str = "",
    conftest: str = "",
    patched_file: str = "",
    file_path: str = "",
) -> dict:
    stack = ACTIVE_STACKS[stack_id]
    stack_dir = Path(stack["dir"])

    if conftest:
        (stack_dir / "tests").mkdir(exist_ok=True)
        (stack_dir / "tests" / "conftest.py").write_text(conftest)

    # Primary path: the Dev agent gives the full fixed file — write it verbatim.
    # No diff to reject, no line-number drift. The diff is only a fallback.
    if patched_file and file_path:
        (stack_dir / file_path).write_text(patched_file)
        return {"applied": True, "method": "full_file"}

    return await _apply_diff(stack_dir, patch_diff)


async def _apply_diff(stack_dir: Path, patch_diff: str) -> dict:
    """Fallback: git apply, then patch --fuzz=3 (line-number-tolerant)."""
    diff_text = patch_diff if patch_diff.endswith("\n") else patch_diff + "\n"
    data = diff_text.encode()

    git = await asyncio.create_subprocess_exec(
        "git", "apply", "--unsafe-paths", "-p1", "-",
        cwd=str(stack_dir),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, git_err = await git.communicate(input=data)
    if git.returncode == 0:
        return {"applied": True, "method": "git_apply"}

    # LLM diffs often have wrong line numbers/context; --fuzz tolerates drift.
    patch = await asyncio.create_subprocess_exec(
        "patch", "-p1", "--fuzz=3", "--no-backup-if-mismatch",
        cwd=str(stack_dir),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, patch_err = await patch.communicate(input=data)
    if patch.returncode == 0:
        return {"applied": True, "method": "patch_fuzz"}

    return {
        "applied": False,
        "stderr": git_err.decode(errors="replace") + patch_err.decode(errors="replace"),
    }


async def run_pytest(stack_id: str, timeout: int = 120) -> dict:
    stack = ACTIVE_STACKS[stack_id]
    compose = _compose(stack)
    loop = asyncio.get_event_loop()
    start = loop.time()

    rc, out, err = await _run(
        compose + ["exec", "-T", "app", "sh", "-lc",
                   "pytest --cov=src --cov-report=json:coverage.json --tb=short -q"],
        timeout=timeout,
    )
    duration_ms = int((loop.time() - start) * 1000)

    cov_rc, cov_out, _ = await _run(
        compose + ["exec", "-T", "app", "cat", "coverage.json"], timeout=30
    )
    post_cov = stack["baseline_cov"]
    if cov_rc == 0:
        try:
            post_cov = float(json.loads(cov_out)["totals"]["percent_covered"])
        except (ValueError, KeyError):
            pass

    failed_assertions = re.findall(r"FAILED\s+(\S+)", out)
    return {
        "passed": rc == 0,
        "coverage_delta": round(post_cov - stack["baseline_cov"], 4),
        "failed_assertions": failed_assertions,
        "duration_ms": duration_ms,
        "stdout_tail": out[-2000:],
        "stderr_tail": err[-1000:],
    }


async def teardown_stack(stack_id: str) -> dict:
    stack = ACTIVE_STACKS.get(stack_id)
    if not stack:
        return {"teardown_clean": True, "note": "stack not found — already down"}

    compose = _compose(stack)
    try:
        await _run(
            compose + ["down", "--volumes", "--remove-orphans", "--timeout", "5"],
            timeout=60,
        )
    except (TimeoutError, OSError):
        pass

    # Belt and suspenders: force-remove anything left on the stack network.
    try:
        import docker

        client = docker.from_env()
        for c in client.containers.list(all=True, filters={"network": f"harness_{stack_id}"}):
            c.remove(force=True)
    except Exception:  # noqa: BLE001 — best-effort cleanup
        pass

    shutil.rmtree(stack["dir"], ignore_errors=True)
    ACTIVE_STACKS.pop(stack_id, None)
    return {"teardown_clean": True}


def build_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("harness", host="0.0.0.0", port=8001)
    mcp.tool()(spin_up_stack)
    mcp.tool()(apply_patch)
    mcp.tool()(run_pytest)
    mcp.tool()(teardown_stack)
    return mcp


def main() -> None:
    build_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()

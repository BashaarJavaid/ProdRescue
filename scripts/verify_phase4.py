"""Phase 4 verification: full harness lifecycle against sample_target via Docker.

spin_up → run_pytest (bug present, fails) → apply_patch → run_pytest (passes) →
teardown → assert no leaked containers/networks.
"""
import asyncio
import difflib
import subprocess
from pathlib import Path

from services.mcp_servers.harness import server

REL = "src/payments/processor.py"
SRC = Path("sample_target") / REL


def _make_fix_diff() -> str:
    original = SRC.read_text()
    fixed = original.replace(
        "    # BUG: no None-guard — `order.total` explodes when order is None.\n"
        "    amount = order.total * 100\n",
        "    if order is None:\n"
        '        raise PaymentError("no order provided")\n'
        "    amount = order.total * 100\n",
    )
    assert fixed != original, "fix substitution did not match source"
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        fixed.splitlines(keepends=True),
        fromfile=f"a/{REL}",
        tofile=f"b/{REL}",
    )
    return "".join(diff)


def _docker_leaks(stack_id: str) -> tuple[list[str], list[str]]:
    nets = subprocess.run(
        ["docker", "network", "ls", "--format", "{{.Name}}"],
        capture_output=True, text=True,
    ).stdout.split()
    conts = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    ).stdout.split()
    leaked_nets = [n for n in nets if stack_id in n]
    leaked_conts = [c for c in conts if stack_id in c]
    return leaked_nets, leaked_conts


async def main() -> None:
    spec = {"file_path": REL, "timeout_seconds": 120}
    spin = await server.spin_up_stack(spec)
    stack_id = spin["stack_id"]
    print(f"spin_up_stack OK → stack_id={stack_id} baseline_cov={spin['baseline_cov']:.1f}%")

    try:
        before = await server.run_pytest(stack_id)
        print(f"run_pytest (buggy) → passed={before['passed']} "
              f"failed={before['failed_assertions']}")
        assert before["passed"] is False, "expected buggy tests to fail"
        assert any("none" in f.lower() for f in before["failed_assertions"])

        applied = await server.apply_patch(stack_id, _make_fix_diff(), conftest="")
        print(f"apply_patch → {applied}")
        assert applied["applied"], applied["stderr"]

        after = await server.run_pytest(stack_id)
        print(f"run_pytest (patched) → passed={after['passed']} "
              f"coverage_delta={after['coverage_delta']}")
        assert after["passed"] is True, after.get("stdout_tail")
        assert after["coverage_delta"] >= 0, "coverage regression"
    finally:
        td = await server.teardown_stack(stack_id)
        print(f"teardown_stack → {td}")

    leaked_nets, leaked_conts = _docker_leaks(stack_id)
    assert not leaked_nets, f"leaked networks: {leaked_nets}"
    assert not leaked_conts, f"leaked containers: {leaked_conts}"
    print("no leaked containers/networks — deterministic teardown OK")
    print("\nPhase 4 verification PASSED")


if __name__ == "__main__":
    asyncio.run(main())

"""LangGraph nodes: triage → dev → qa → (retry|pr).

Each node calls only its scoped MCP server (via ``mcp_call``) and uses the LLM
purely for structured generation. Tools are invoked explicitly by node code.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import uuid4

from services.agents.llm import structured
from services.agents.mcp_clients import mcp_call, resolve_path
from services.agents.persistence import mark_resolved, store_harness_result
from services.agents.prompts import (
    DEV_SYSTEM_PROMPT,
    PR_BODY_TEMPLATE,
    TRIAGE_SYSTEM_PROMPT,
)
from services.agents.state import AgentState
from services.agents.tracing import traceable
from services.api.metrics import TIME_TO_PR, emit_prometheus_metrics
from services.config import settings
from services.schemas.models import HarnessResult, PatchOutput, TriageOutput


@traceable("triage_node")
async def triage_node(state: AgentState) -> dict:
    log = state["log"]
    similar = await mcp_call(
        "triage", "logs_db", "semantic_search_logs",
        {"query": log["message"], "top_k": 5},
    )

    result: TriageOutput = await asyncio.wait_for(
        structured(
            TriageOutput,
            TRIAGE_SYSTEM_PROMPT,
            f"Error log:\n{log}\n\nSimilar past incidents:\n{similar}\n\n"
            "Produce a root cause analysis and HarnessSpec.",
        ),
        timeout=settings.llm_timeout_seconds,
    )

    return {
        "root_cause": result.root_cause,
        "affected_file": result.affected_file,
        "harness_spec": result.harness_spec.model_dump(),
        "messages": state.get("messages", []) + [
            {"role": "triage", "content": result.root_cause}
        ],
    }


@traceable("dev_node")
async def dev_node(state: AgentState) -> dict:
    spec = dict(state["harness_spec"])
    # Triage's file_path is nondeterministic (drops src/, keeps a leading app/);
    # pin it to a real file before fetching, and propagate the fix so qa+pr agree.
    listing = await mcp_call("dev", "github", "list_files", {})
    resolved = resolve_path(spec["file_path"], listing["files"])
    if not resolved:
        raise FileNotFoundError(
            f"triage picked '{spec['file_path']}', which is not in the repo"
        )
    spec["file_path"] = resolved
    source = await mcp_call(
        "dev", "github", "get_file_contents", {"path": resolved}
    )

    retry_context = ""
    prev = state.get("harness_result")
    if prev:
        retry_context = (
            "PREVIOUS PATCH FAILED. Harness result:\n"
            f"Failed assertions: {prev['failed_assertions']}\n"
            f"Coverage delta: {prev['coverage_delta']}\n"
            f"Duration: {prev['duration_ms']}ms\n"
            "You MUST address these failures in the new patch."
        )

    result: PatchOutput = await asyncio.wait_for(
        structured(
            PatchOutput,
            DEV_SYSTEM_PROMPT,
            f"Root cause: {state['root_cause']}\n"
            f"HarnessSpec: {spec}\n"
            f"Source file ({spec['file_path']}):\n{source['content']}\n\n"
            f"{retry_context}",
        ),
        timeout=settings.llm_timeout_seconds,
    )

    return {
        "harness_spec": spec,  # carries the resolved file_path forward to qa + pr
        "patched_file": result.patched_file,
        "patch": result.patch_diff,
        "fixture": result.conftest,
        "explanation": result.explanation,
        "original_len": len(source["content"]),
    }


@traceable("qa_node")
async def qa_node(state: AgentState) -> dict:
    spec = state["harness_spec"]
    timeout = float(spec.get("timeout_seconds", 120))
    stack_id = None
    started = time.monotonic()

    # Cheap scope guard before spending a Docker stack: reject a patch that balloons
    # the file or (via its diff) touches anything but the affected file + conftest.
    from services.agents.patching import check_patch_scope

    scope_reason = check_patch_scope(
        spec["file_path"],
        state.get("patched_file", ""),
        state.get("original_len", 0),
        state.get("patch", ""),
        settings.max_patch_growth_ratio,
    )
    pytest_result: dict[str, Any]
    if scope_reason:
        pytest_result = {
            "passed": False,
            "coverage_delta": -999.0,
            "failed_assertions": [f"patch rejected: {scope_reason}"],
            "duration_ms": 0,
        }
    else:
        try:
            spin = await mcp_call("qa", "harness", "spin_up_stack", {"spec": spec})
            stack_id = spin["stack_id"]

            await mcp_call(
                "qa", "harness", "apply_patch",
                {
                    "stack_id": stack_id,
                    "patched_file": state.get("patched_file", ""),
                    "file_path": spec["file_path"],
                    "patch_diff": state["patch"],
                    "conftest": state["fixture"],
                },
            )

            pytest_result = await asyncio.wait_for(
                mcp_call("qa", "harness", "run_pytest", {"stack_id": stack_id}),
                timeout=timeout,
            )
        except TimeoutError:
            pytest_result = {
                "passed": False,
                "coverage_delta": -999.0,
                "failed_assertions": ["Test run timed out"],
                "duration_ms": int(timeout * 1000),
            }
        except Exception as exc:  # noqa: BLE001 — surface any harness error as a failure
            pytest_result = {
                "passed": False,
                "coverage_delta": -999.0,
                "failed_assertions": [f"harness error: {exc}"],
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
        finally:
            if stack_id:
                await mcp_call("qa", "harness", "teardown_stack", {"stack_id": stack_id})

    duration_ms = pytest_result.get("duration_ms") or int((time.monotonic() - started) * 1000)
    harness_result = HarnessResult(
        run_id=uuid4(),
        passed=pytest_result["passed"],
        coverage_delta=pytest_result.get("coverage_delta", 0.0),
        failed_assertions=pytest_result.get("failed_assertions", []),
        duration_ms=duration_ms,
        teardown_clean=True,
        retry_attempt=state.get("retry_count", 0),
        patch_diff=state.get("patch"),
    )

    await store_harness_result(harness_result, state.get("log_id"), state.get("patch"))
    emit_prometheus_metrics(harness_result, service=state["log"].get("service", "unknown"))

    return {
        "harness_result": harness_result.model_dump(mode="json"),
        "retry_count": state.get("retry_count", 0) + 1,
    }


@traceable("pr_node")
async def pr_node(state: AgentState) -> dict:
    log = state["log"]
    harness = state["harness_result"]
    spec = state["harness_spec"]
    branch = f"prodrescue/{log['log_id']}"

    failed = harness.get("failed_assertions", [])
    pr_body = PR_BODY_TEMPLATE.format(
        service=log.get("service", "unknown"),
        root_cause=state.get("root_cause", ""),
        attempts=state.get("retry_count", 0),
        explanation=state.get("explanation", ""),
        passed_icon="✅" if harness.get("passed") else "❌",
        coverage_delta=harness.get("coverage_delta", 0.0),
        duration_ms=harness.get("duration_ms", 0),
        retry_attempt=harness.get("retry_attempt", 0),
        failed_assertions=(
            "\n".join(f"- `{a}`" for a in failed) or "None (passed first attempt)"
        ),
    )

    await mcp_call("pr", "github", "create_branch", {"name": branch})

    # Push the patched file. The Dev agent emits the full fixed file, so we upload
    # it directly — no diff-apply on the PR path. Fall back to applying the diff
    # only if the full file is somehow missing.
    patched = state.get("patched_file")
    if not patched:
        source = await mcp_call("pr", "github", "get_file_contents", {"path": spec["file_path"]})
        from services.agents.patching import apply_unified_diff

        patched = apply_unified_diff(source["content"], state["patch"], spec["file_path"])
    await mcp_call(
        "pr", "github", "put_file",
        {
            "branch": branch,
            "path": spec["file_path"],
            "content": patched,
            "message": f"fix: {state.get('root_cause', 'ProdRescue patch')[:72]}",
        },
    )

    pr = await mcp_call(
        "pr", "github", "create_pull_request",
        {
            "title": f"[ProdRescue] fix: {log.get('service', 'service')} crash",
            "body": pr_body,
            "branch": branch,
            "patch_diff": state["patch"],
        },
    )

    if state.get("log_id"):
        await mark_resolved(state["log_id"])

    if state.get("started_at"):
        TIME_TO_PR.observe(time.time() - state["started_at"])

    return {"pr_url": pr.get("html_url")}

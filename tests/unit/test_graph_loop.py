"""Full LangGraph loop with stubbed LLM/MCP — retry-then-pass and give-up paths."""
import pytest
from services.agents import nodes, patching
from services.agents.graph import build_graph
from services.schemas.models import HarnessSpec, PatchOutput, TriageOutput


@pytest.fixture
def stub_pipeline(monkeypatch):
    counters = {"dev": 0, "run_pytest": 0}
    outcomes = {"sequence": [False, True]}

    async def fake_structured(response_model, system, user, **kw):
        if response_model is TriageOutput:
            return TriageOutput(
                root_cause="None order", affected_file="src/payments/processor.py",
                harness_spec=HarnessSpec(file_path="src/payments/processor.py"),
            )
        counters["dev"] += 1
        return PatchOutput(
            patched_file="patched", patch_diff="<diff>", conftest="<c>", explanation="fix",
        )

    async def fake_mcp(agent, server, tool, args=None):
        if tool == "semantic_search_logs":
            return []
        if tool == "get_file_contents":
            return {"content": "orig", "path": args["path"]}
        if tool == "spin_up_stack":
            return {"stack_id": "s1"}
        if tool == "run_pytest":
            i = counters["run_pytest"]
            counters["run_pytest"] += 1
            seq = outcomes["sequence"]
            passed = seq[min(i, len(seq) - 1)]
            return {
                "passed": passed,
                "coverage_delta": 1.0 if passed else 0.0,
                "failed_assertions": [] if passed else ["test_charge_none_raises"],
                "duration_ms": 1000,
            }
        if tool == "create_pull_request":
            return {"html_url": "https://github.com/x/y/pull/1"}
        return {"ok": True}

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(nodes, "structured", fake_structured)
    monkeypatch.setattr(nodes, "mcp_call", fake_mcp)
    monkeypatch.setattr(nodes, "store_harness_result", noop)
    monkeypatch.setattr(nodes, "mark_resolved", noop)
    monkeypatch.setattr(patching, "apply_unified_diff", lambda o, d, p: "patched")
    return counters, outcomes


async def test_retry_then_pass_opens_pr(stub_pipeline):
    counters, _ = stub_pipeline
    graph = build_graph(checkpointer=None)
    final = await graph.ainvoke(
        {"log": {"service": "payments", "message": "boom", "log_id": "L1"},
         "log_id": "L1", "retry_count": 0, "messages": []},
        config={"configurable": {"thread_id": "L1"}},
    )
    assert final["pr_url"] == "https://github.com/x/y/pull/1"
    assert counters["dev"] == 2  # initial + one retry
    assert final["retry_count"] == 2


async def test_persistent_failure_gives_up(stub_pipeline):
    counters, outcomes = stub_pipeline
    outcomes["sequence"] = [False]  # never passes
    graph = build_graph(checkpointer=None)
    final = await graph.ainvoke(
        {"log": {"service": "payments", "message": "boom", "log_id": "L2"},
         "log_id": "L2", "retry_count": 0, "messages": []},
        config={"configurable": {"thread_id": "L2"}},
    )
    assert final.get("pr_url") is None
    assert final["retry_count"] == 3

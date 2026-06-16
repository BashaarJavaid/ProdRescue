"""Phase 3 verification: routing truth table + full stubbed self-healing loop."""
import asyncio

from langgraph.graph import END
from services.agents import nodes, patching
from services.agents.graph import build_graph, route_after_qa
from services.schemas.models import HarnessSpec, PatchOutput, TriageOutput


def test_routing() -> None:
    # pass + non-negative coverage → pr
    assert route_after_qa({"harness_result": {"passed": True, "coverage_delta": 0.0}}) == "pr"
    # pass but coverage regression → retry
    assert route_after_qa(
        {"harness_result": {"passed": True, "coverage_delta": -1.0}, "retry_count": 0}
    ) == "dev"
    # fail, retries left → retry
    assert route_after_qa(
        {"harness_result": {"passed": False, "coverage_delta": 1.0}, "retry_count": 2}
    ) == "dev"
    # fail, retries exhausted → END
    assert route_after_qa(
        {"harness_result": {"passed": False, "coverage_delta": 1.0}, "retry_count": 3}
    ) == END
    print("route_after_qa truth table OK")


def _install_stubs(pytest_outcomes: list[bool]) -> dict:
    counters = {"dev": 0, "run_pytest": 0}

    async def fake_structured(response_model, system, user, **kw):
        if response_model is TriageOutput:
            return TriageOutput(
                root_cause="charge() dereferences None order",
                affected_file="src/payments/processor.py",
                harness_spec=HarnessSpec(file_path="src/payments/processor.py"),
            )
        if response_model is PatchOutput:
            counters["dev"] += 1
            return PatchOutput(patch_diff="<diff>", conftest="<conftest>", explanation="fix")
        raise AssertionError(response_model)

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
            passed = pytest_outcomes[min(i, len(pytest_outcomes) - 1)]
            return {
                "passed": passed,
                "coverage_delta": 1.0 if passed else 0.0,
                "failed_assertions": [] if passed else ["test_charge failed"],
                "duration_ms": 1234,
            }
        if tool == "create_pull_request":
            return {"html_url": "https://github.com/x/y/pull/1"}
        return {"ok": True}

    async def noop(*a, **k):
        return None

    nodes.structured = fake_structured
    nodes.mcp_call = fake_mcp
    nodes.store_harness_result = noop
    nodes.mark_resolved = noop
    patching.apply_unified_diff = lambda original, diff, path: "patched"
    return counters


async def test_loop_retries_then_passes() -> None:
    counters = _install_stubs([False, True])  # fail once, then pass
    graph = build_graph(checkpointer=None)
    final = await graph.ainvoke(
        {"log": {"service": "payments", "message": "boom", "log_id": "L1"},
         "log_id": "L1", "retry_count": 0, "messages": []},
        config={"configurable": {"thread_id": "L1"}},
    )
    assert final["pr_url"] == "https://github.com/x/y/pull/1", final
    assert counters["dev"] == 2, f"expected 2 dev passes (retry), got {counters['dev']}"
    assert final["retry_count"] == 2
    print(f"self-healing loop OK → dev ran {counters['dev']}x, PR={final['pr_url']}")


async def test_loop_gives_up() -> None:
    _install_stubs([False])  # always fail
    graph = build_graph(checkpointer=None)
    final = await graph.ainvoke(
        {"log": {"service": "payments", "message": "boom", "log_id": "L2"},
         "log_id": "L2", "retry_count": 0, "messages": []},
        config={"configurable": {"thread_id": "L2"}},
    )
    assert final.get("pr_url") is None
    assert final["retry_count"] == 3, final["retry_count"]
    print(f"max-retry give-up OK → retry_count={final['retry_count']}, no PR")


if __name__ == "__main__":
    test_routing()
    asyncio.run(test_loop_retries_then_passes())
    asyncio.run(test_loop_gives_up())
    print("\nPhase 3 verification PASSED")

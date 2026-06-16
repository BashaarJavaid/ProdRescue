"""LangGraph state machine — the self-healing loop.

triage → dev → qa →(pass)→ pr → END
                  └─(fail, retry<3)→ dev
                  └─(fail, retry≥3)→ END

State is checkpointed to Postgres (AsyncPostgresSaver) so a worker restart
resumes mid-incident. ``route_after_qa`` is the coverage-gated retry edge.
"""
from __future__ import annotations

import time

from langgraph.graph import END, StateGraph

from services.agents.nodes import dev_node, pr_node, qa_node, triage_node
from services.agents.state import AgentState
from services.api.metrics import ACTIVE_PIPELINES, RETRY_COUNT
from services.config import settings

MAX_RETRIES = 3


def route_after_qa(state: AgentState) -> str:
    """Coverage-gated conditional edge (spec §9.3)."""
    result = state.get("harness_result") or {}
    if result.get("passed") and result.get("coverage_delta", -1) >= 0:
        return "pr"
    if state.get("retry_count", 0) < MAX_RETRIES:
        return "dev"  # retry with failure telemetry
    return END  # give up after MAX_RETRIES


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)
    graph.add_node("triage", triage_node)
    graph.add_node("dev", dev_node)
    graph.add_node("qa", qa_node)
    graph.add_node("pr", pr_node)

    graph.set_entry_point("triage")
    graph.add_edge("triage", "dev")
    graph.add_edge("dev", "qa")
    graph.add_conditional_edges("qa", route_after_qa, {"pr": "pr", "dev": "dev", END: END})
    graph.add_edge("pr", END)

    return graph.compile(checkpointer=checkpointer)


async def run_graph(log_payload: dict) -> dict:
    """Entry point invoked by the Celery worker."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    config = {"configurable": {"thread_id": log_payload["log_id"]}}
    initial_state: AgentState = {
        "log": log_payload,
        "log_id": log_payload["log_id"],
        "retry_count": 0,
        "started_at": time.time(),
        "messages": [],
    }

    ACTIVE_PIPELINES.inc()
    try:
        async with AsyncPostgresSaver.from_conn_string(settings.psycopg_dsn) as saver:
            await saver.setup()
            graph = build_graph(checkpointer=saver)
            final_state = await graph.ainvoke(initial_state, config=config)
    finally:
        ACTIVE_PIPELINES.dec()

    RETRY_COUNT.observe(final_state.get("retry_count", 0))
    return {
        "pr_url": final_state.get("pr_url"),
        "root_cause": final_state.get("root_cause"),
        "retry_count": final_state.get("retry_count", 0),
        "harness_result": final_state.get("harness_result"),
    }

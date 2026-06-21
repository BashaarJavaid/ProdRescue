"""LangGraph state machine — the self-healing loop.

triage → dev → qa →(pass)→ pr → END
                  └─(fail, retry<3)→ dev
                  └─(fail, retry≥3)→ END

State is checkpointed to Postgres (AsyncPostgresSaver) so a worker restart
resumes mid-incident. ``route_after_qa`` is the coverage-gated retry edge.
"""
from __future__ import annotations

import logging
import time

from langgraph.graph import END, StateGraph

from services.agents.nodes import dev_node, pr_node, qa_node, triage_node
from services.agents.state import AgentState
from services.api.metrics import ACTIVE_PIPELINES, PIPELINE_FAILURES, RETRY_COUNT
from services.config import settings
from services.logging_setup import set_log_id

logger = logging.getLogger(__name__)


def route_after_qa(state: AgentState) -> str:
    """Coverage-gated conditional edge (spec §9.3)."""
    result = state.get("harness_result") or {}
    if result.get("passed") and result.get("coverage_delta", -1) >= 0:
        return "pr"
    if state.get("retry_count", 0) < settings.max_retries:
        return "dev"  # retry with failure telemetry
    return END  # give up after settings.max_retries


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

    set_log_id(log_payload["log_id"])
    service = log_payload.get("service", "unknown")
    config = {"configurable": {"thread_id": log_payload["log_id"]}}
    initial_state: AgentState = {
        "log": log_payload,
        "log_id": log_payload["log_id"],
        "retry_count": 0,
        "started_at": time.time(),
        "messages": [],
    }

    ACTIVE_PIPELINES.inc()
    final_state: dict = {}
    try:
        async with AsyncPostgresSaver.from_conn_string(settings.psycopg_dsn) as saver:
            await saver.setup()
            graph = build_graph(checkpointer=saver)
            final_state = await graph.ainvoke(initial_state, config=config)
    except Exception as exc:  # noqa: BLE001 — a node crash must not kill the worker
        # Any node failure (e.g. triage picking a non-existent file_path) is recorded
        # and counted, not raised as an unhandled Celery traceback.
        PIPELINE_FAILURES.labels(service=service, reason="exception").inc()
        logger.exception("pipeline failed")
        final_state = {"error": str(exc)}
    finally:
        ACTIVE_PIPELINES.dec()
        # Release the concurrency slot the API acquired for this incident (best-effort).
        from services.api.ratelimit import release_slot

        await release_slot()
        # ponytail: asyncpg pool is bound to the loop that created it. Celery runs
        # asyncio.run() (a fresh loop) per task, so close it here or task #2 reuses
        # a dead-loop pool. Per-task pool churn is one pipeline/task — negligible.
        from services.api.database import db

        await db.close()

    # Reaching END without a PR (retries exhausted) is also a failure worth alerting on.
    if not final_state.get("pr_url") and not final_state.get("error"):
        PIPELINE_FAILURES.labels(service=service, reason="gave_up").inc()
        logger.warning("pipeline gave up after %s retries", final_state.get("retry_count", 0))

    RETRY_COUNT.observe(final_state.get("retry_count", 0))
    return {
        "pr_url": final_state.get("pr_url"),
        "root_cause": final_state.get("root_cause"),
        "retry_count": final_state.get("retry_count", 0),
        "harness_result": final_state.get("harness_result"),
        "error": final_state.get("error"),
    }

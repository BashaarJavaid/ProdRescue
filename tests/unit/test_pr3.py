"""Gate C: readiness probe, LLM-call timeout, graceful pipeline failure + metric."""
import asyncio

import pytest
from fastapi.testclient import TestClient
from services.agents import graph, nodes
from services.api import main
from services.api.metrics import PIPELINE_FAILURES
from services.config import settings


def test_ready_returns_503_when_deps_down():
    # No Postgres/RabbitMQ in the unit env → readiness must fail (not lie like /health).
    resp = TestClient(main.app).get("/ready")
    assert resp.status_code == 503
    assert resp.json()["db"].startswith("error")


async def test_triage_llm_call_times_out(monkeypatch):
    monkeypatch.setattr(settings, "llm_timeout_seconds", 0.05)

    async def hang(*a, **k):
        await asyncio.sleep(5)

    async def fake_mcp(*a, **k):
        return []

    monkeypatch.setattr(nodes, "mcp_call", fake_mcp)
    monkeypatch.setattr(nodes, "structured", hang)
    with pytest.raises(asyncio.TimeoutError):
        await nodes.triage_node({"log": {"message": "boom"}})


async def test_run_graph_swallows_node_crash_and_counts_it(monkeypatch):
    # A node exception must be recorded + counted, not raised out of the worker.
    pytest.importorskip("langgraph.checkpoint.postgres")

    class _FakeSaver:
        async def setup(self):
            pass

    class _FakeCtx:
        async def __aenter__(self):
            return _FakeSaver()

        async def __aexit__(self, *a):
            return False

    from langgraph.checkpoint.postgres import aio
    monkeypatch.setattr(aio.AsyncPostgresSaver, "from_conn_string", staticmethod(lambda dsn: _FakeCtx()))

    class _Boom:
        async def ainvoke(self, *a, **k):
            raise RuntimeError("triage picked a bogus file")

    monkeypatch.setattr(graph, "build_graph", lambda checkpointer=None: _Boom())

    before = PIPELINE_FAILURES.labels(service="payments", reason="exception")._value.get()
    out = await graph.run_graph({"log_id": "L9", "service": "payments"})
    after = PIPELINE_FAILURES.labels(service="payments", reason="exception")._value.get()

    assert out["error"] == "triage picked a bogus file"
    assert out["pr_url"] is None
    assert after == before + 1

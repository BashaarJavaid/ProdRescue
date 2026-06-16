"""Triage node: searches logs via MCP and produces a HarnessSpec."""
import pytest
from services.agents import nodes
from services.schemas.models import HarnessSpec, TriageOutput


@pytest.fixture
def stub(monkeypatch):
    calls = {}

    async def fake_mcp(agent, server, tool, args=None):
        calls["mcp"] = (agent, server, tool)
        return [{"message": "past incident", "similarity": 0.9}]

    async def fake_structured(response_model, system, user, **kw):
        calls["user"] = user
        return TriageOutput(
            root_cause="None order dereferenced in charge()",
            affected_file="src/payments/processor.py",
            harness_spec=HarnessSpec(file_path="src/payments/processor.py"),
        )

    monkeypatch.setattr(nodes, "mcp_call", fake_mcp)
    monkeypatch.setattr(nodes, "structured", fake_structured)
    return calls


async def test_triage_node_outputs_spec(stub):
    state = {"log": {"message": "AttributeError NoneType total", "service": "payments"},
             "messages": []}
    out = await nodes.triage_node(state)

    assert out["root_cause"].startswith("None order")
    assert out["harness_spec"]["file_path"] == "src/payments/processor.py"
    assert out["messages"][-1]["role"] == "triage"
    # Triage may only reach the logs_db server.
    assert stub["mcp"] == ("triage", "logs_db", "semantic_search_logs")
    # Similar incidents were fed into the prompt.
    assert "past incident" in stub["user"]

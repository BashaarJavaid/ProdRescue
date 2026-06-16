"""Dev node: fetches source via MCP and folds prior failures into the retry prompt."""
import pytest
from services.agents import nodes
from services.schemas.models import PatchOutput


@pytest.fixture
def stub(monkeypatch):
    calls = {}

    async def fake_mcp(agent, server, tool, args=None):
        calls.setdefault("mcp", []).append((agent, server, tool))
        return {"content": "def charge(order):\n    return order.total\n", "path": args["path"]}

    async def fake_structured(response_model, system, user, **kw):
        calls["user"] = user
        return PatchOutput(patch_diff="--- a\n+++ b\n", conftest="x=1", explanation="fix")

    monkeypatch.setattr(nodes, "mcp_call", fake_mcp)
    monkeypatch.setattr(nodes, "structured", fake_structured)
    return calls


async def test_dev_node_first_attempt(stub):
    state = {
        "harness_spec": {"file_path": "src/payments/processor.py"},
        "root_cause": "None order",
    }
    out = await nodes.dev_node(state)
    assert out["patch"] == "--- a\n+++ b\n"
    assert out["fixture"] == "x=1"
    assert stub["mcp"] == [("dev", "github", "get_file_contents")]
    assert "PREVIOUS PATCH FAILED" not in stub["user"]


async def test_dev_node_retry_includes_failure_telemetry(stub):
    state = {
        "harness_spec": {"file_path": "src/payments/processor.py"},
        "root_cause": "None order",
        "harness_result": {
            "failed_assertions": ["test_charge_none_raises"],
            "coverage_delta": 0.0,
            "duration_ms": 1500,
        },
    }
    await nodes.dev_node(state)
    assert "PREVIOUS PATCH FAILED" in stub["user"]
    assert "test_charge_none_raises" in stub["user"]

"""MCP call-site scoping and the GitHub dry-run fallback."""
import pytest
from services.agents.mcp_clients import (
    AGENT_MCP_SERVERS,
    ScopeError,
    mcp_call,
)


def test_scope_map_is_least_privilege():
    assert AGENT_MCP_SERVERS["triage"] == ["logs_db"]
    assert AGENT_MCP_SERVERS["dev"] == ["github"]
    assert AGENT_MCP_SERVERS["qa"] == ["harness"]
    assert AGENT_MCP_SERVERS["pr"] == ["github"]


@pytest.mark.parametrize(
    "agent,server",
    [("triage", "github"), ("triage", "harness"), ("dev", "harness"),
     ("qa", "github"), ("pr", "logs_db")],
)
async def test_out_of_scope_blocked(agent, server):
    with pytest.raises(ScopeError):
        await mcp_call(agent, server, "any_tool", {})


async def test_github_dryrun_get_file_contents(monkeypatch):
    # No token → dry-run path reads the local target checkout.
    from services.agents import mcp_clients
    monkeypatch.setattr(mcp_clients.settings, "github_token", "")
    out = await mcp_call("dev", "github", "get_file_contents",
                         {"path": "src/payments/processor.py"})
    assert "def charge" in out["content"]


async def test_github_dryrun_pull_request(monkeypatch, tmp_path):
    from services.agents import mcp_clients
    monkeypatch.setattr(mcp_clients.settings, "github_token", "")
    monkeypatch.setattr(mcp_clients, "_DRYRUN_DIR", tmp_path / "dryrun")
    pr = await mcp_call("pr", "github", "create_pull_request",
                        {"title": "t", "body": "b", "branch": "prodrescue/x", "patch_diff": "d"})
    assert pr["dry_run"] is True
    assert (tmp_path / "dryrun" / "prodrescue_x.md").exists()

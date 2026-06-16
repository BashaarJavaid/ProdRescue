"""Phase 5 verification: MCP scoping, GitHub dry-run, and the real Logs-DB
MCP server over streamable-http."""
import asyncio
from datetime import UTC, datetime

from services.agents.mcp_clients import ScopeError, mcp_call
from services.api.embeddings import embed_and_store
from services.schemas.models import ErrorLog


async def test_scoping() -> None:
    for agent, server in [("triage", "github"), ("dev", "harness"), ("pr", "logs_db")]:
        try:
            await mcp_call(agent, server, "whatever", {})
            raise AssertionError(f"{agent}->{server} should have been blocked")
        except ScopeError:
            pass
    print("MCP scoping OK (out-of-scope calls blocked)")


async def test_github_dryrun() -> None:
    # get_file_contents reads the local target checkout
    src = await mcp_call("dev", "github", "get_file_contents",
                         {"path": "src/payments/processor.py"})
    assert "def charge" in src["content"]
    # create_pull_request writes a dry-run artifact
    pr = await mcp_call("pr", "github", "create_pull_request",
                        {"title": "t", "body": "b", "branch": "prodrescue/test-1",
                         "patch_diff": "--- a\n+++ b\n"})
    assert pr["dry_run"] is True and "dry-run" in pr["html_url"]
    print(f"GitHub dry-run OK → {pr['html_url']}")


async def seed() -> None:
    for msg in [
        "NullPointerException in PaymentProcessor.charge()",
        "AttributeError: 'NoneType' object has no attribute 'total'",
        "ConnectionError: redis timeout in cache layer",
    ]:
        await embed_and_store(ErrorLog(
            service="payments", message=msg, stacktrace="",
            occurred_at=datetime.now(UTC), metadata={},
        ))
    print("seeded 3 incidents")


async def test_logs_db_transport() -> None:
    # Real streamable-http call through mcp_call → running FastMCP server.
    rows = await mcp_call("triage", "logs_db", "semantic_search_logs",
                          {"query": "NoneType has no attribute total", "top_k": 3})
    assert isinstance(rows, list) and len(rows) >= 1, rows
    assert "similarity" in rows[0]
    top = rows[0]["message"]
    print(f"semantic_search_logs OK → top match: {top!r} (sim={rows[0]['similarity']:.3f})")

    freq = await mcp_call("triage", "logs_db", "get_error_frequency",
                          {"service": "payments", "hours": 24})
    assert freq["total"] >= 3, freq
    print(f"get_error_frequency OK → {freq}")


async def main() -> None:
    await test_scoping()
    await test_github_dryrun()
    await seed()
    await test_logs_db_transport()
    print("\nPhase 5 verification PASSED")


if __name__ == "__main__":
    asyncio.run(main())

"""Logs-DB MCP server.

Exposes pgvector semantic search and TimescaleDB analytics to the Triage agent.
Core functions are transport-agnostic; the FastMCP wrapper is built lazily.
"""
from __future__ import annotations

from services.api.database import db
from services.api.embeddings import embed_async


def _row_to_dict(row) -> dict:
    out = {}
    for k, v in dict(row).items():
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
        if k == "id":
            out[k] = str(v)
    return out


async def semantic_search_logs(query: str, top_k: int = 5) -> list[dict]:
    """Embed the query and return the most cosine-similar historical error logs."""
    embedding = await embed_async(query)
    rows = await db.fetch(
        """
        SELECT id, message, occurred_at, service, resolved,
               1 - (embedding <=> $1) AS similarity
        FROM error_logs
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> $1
        LIMIT $2
        """,
        embedding,
        top_k,
    )
    return [_row_to_dict(r) for r in rows]


async def get_error_frequency(service: str, hours: int = 24) -> dict:
    """Error counts for a service over the last N hours (incident severity signal)."""
    row = await db.fetchrow(
        """
        SELECT COUNT(*)                                  AS total,
               COUNT(*) FILTER (WHERE resolved = TRUE)   AS resolved,
               COUNT(*) FILTER (WHERE resolved = FALSE)  AS unresolved
        FROM error_logs
        WHERE service = $1
          AND occurred_at > NOW() - ($2 || ' hours')::INTERVAL
        """,
        service,
        str(hours),
    )
    return dict(row) if row else {"total": 0, "resolved": 0, "unresolved": 0}


async def get_similar_resolutions(query: str, top_k: int = 3) -> list[dict]:
    """Past incidents similar to the query that were resolved, with the fixing PRs."""
    embedding = await embed_async(query)
    rows = await db.fetch(
        """
        SELECT el.message, el.occurred_at, hr.patch_diff, hr.pr_url,
               1 - (el.embedding <=> $1) AS similarity
        FROM error_logs el
        JOIN harness_results hr ON hr.log_id = el.id
        WHERE el.resolved = TRUE AND hr.passed = TRUE
        ORDER BY el.embedding <=> $1
        LIMIT $2
        """,
        embedding,
        top_k,
    )
    return [_row_to_dict(r) for r in rows]


def build_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("logs_db", host="0.0.0.0", port=8002)
    mcp.tool()(semantic_search_logs)
    mcp.tool()(get_error_frequency)
    mcp.tool()(get_similar_resolutions)
    return mcp


def main() -> None:
    build_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()

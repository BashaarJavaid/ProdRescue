"""Logs-DB MCP tool functions with a stubbed database."""
from datetime import UTC, datetime

import pytest
from services.mcp_servers.logs_db import server


@pytest.fixture
def fake_db(monkeypatch):
    rows = [
        {"id": "11111111-1111-1111-1111-111111111111", "message": "AttributeError",
         "occurred_at": datetime(2026, 6, 1, tzinfo=UTC), "service": "payments",
         "resolved": False, "similarity": 0.91},
    ]

    async def fake_fetch(query, *args):
        return rows

    async def fake_fetchrow(query, *args):
        return {"total": 5, "resolved": 2, "unresolved": 3}

    monkeypatch.setattr(server.db, "fetch", fake_fetch)
    monkeypatch.setattr(server.db, "fetchrow", fake_fetchrow)
    return rows


async def test_semantic_search_serialises_rows(fake_db):
    out = await server.semantic_search_logs("nonetype total", top_k=3)
    assert len(out) == 1
    assert out[0]["similarity"] == 0.91
    assert out[0]["occurred_at"] == "2026-06-01T00:00:00+00:00"  # isoformatted


async def test_error_frequency(fake_db):
    freq = await server.get_error_frequency("payments", hours=24)
    assert freq == {"total": 5, "resolved": 2, "unresolved": 3}


async def test_similar_resolutions(fake_db):
    out = await server.get_similar_resolutions("nonetype total", top_k=2)
    assert isinstance(out, list)

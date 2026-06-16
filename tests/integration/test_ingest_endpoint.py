"""Integration: /ingest stores an embedded row in Postgres.

Requires a Postgres reachable at DATABASE_URL with infra/db/init.sql applied.
Run with: pytest tests/integration -m integration
(skipped automatically unless RUN_INTEGRATION=1).
"""
import os
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1", reason="integration stack not running"
)


async def test_embed_and_store_roundtrip():
    from services.api.database import db
    from services.api.embeddings import embed_and_store
    from services.schemas.models import ErrorLog

    log_id = await embed_and_store(
        ErrorLog(service="payments", message="integration test crash",
                 stacktrace="", occurred_at=datetime.now(UTC), metadata={"k": "v"})
    )
    row = await db.fetchrow(
        "SELECT service, metadata, embedding IS NOT NULL AS has_emb "
        "FROM error_logs WHERE id=$1", log_id,
    )
    assert row["has_emb"]
    assert row["metadata"] == {"k": "v"}
    await db.close()

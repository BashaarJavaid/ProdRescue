"""Phase 2 verification: embed_and_store + FastAPI endpoints (no broker needed)."""
import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from services.api import main
from services.api.database import db
from services.api.embeddings import embed_and_store
from services.schemas.models import ErrorLog


async def _store() -> None:
    log = ErrorLog(
        service="payments",
        message="NullPointerException in PaymentProcessor.charge()",
        stacktrace="at payments/processor.py:142",
        occurred_at=datetime.now(UTC),
        metadata={"env": "prod", "region": "us-east-1"},
    )
    log_id = await embed_and_store(log)
    row = await db.fetchrow(
        "SELECT service, message, metadata, embedding IS NOT NULL AS has_emb "
        "FROM error_logs WHERE id=$1",
        log_id,
    )
    assert row["has_emb"], "embedding not stored"
    assert row["metadata"] == {"env": "prod", "region": "us-east-1"}, "jsonb roundtrip failed"
    print(f"embed_and_store OK → id={log_id} service={row['service']}")
    await db.close()


def _endpoints() -> None:
    client = TestClient(main.app)
    assert client.get("/health").json() == {"status": "ok"}
    print("GET /health OK")

    m = client.get("/metrics")
    assert m.status_code == 200 and b"prodrescue_active_pipelines" in m.content
    print("GET /metrics OK (exposes prodrescue metrics)")

    # /ingest: stub the Celery enqueue so no broker is required.
    fake = MagicMock()
    fake.delay.return_value = MagicMock(id="fake-task-123")
    with patch("services.api.tasks.run_agent_pipeline", fake):
        resp = client.post(
            "/ingest",
            json={
                "service": "payments",
                "message": "AttributeError: 'NoneType' object has no attribute 'total'",
                "stacktrace": "at payments/processor.py:142 in charge",
                "occurred_at": "2026-06-16T10:30:00Z",
                "metadata": {},
            },
        )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["task_id"] == "fake-task-123" and body["status"] == "queued"
    print(f"POST /ingest OK → {body}")


if __name__ == "__main__":
    asyncio.run(_store())
    _endpoints()
    print("\nPhase 2 verification PASSED")

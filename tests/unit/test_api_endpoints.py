"""FastAPI endpoints that need no DB/broker."""
from fastapi.testclient import TestClient
from services.api import main
from services.config import settings


def test_health():
    client = TestClient(main.app)
    assert client.get("/health").json() == {"status": "ok"}


def test_metrics_exposition():
    client = TestClient(main.app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"prodrescue_active_pipelines" in resp.content


_BODY = {"service": "payments", "message": "boom", "occurred_at": "2026-06-20T00:00:00Z"}


def test_ingest_rejects_missing_key(monkeypatch):
    # With a key configured, the auth dependency short-circuits before any DB/broker.
    monkeypatch.setattr(settings, "ingest_api_key", "secret")
    client = TestClient(main.app)
    assert client.post("/ingest", json=_BODY).status_code == 401


def test_ingest_rejects_wrong_key(monkeypatch):
    monkeypatch.setattr(settings, "ingest_api_key", "secret")
    client = TestClient(main.app)
    resp = client.post("/ingest", json=_BODY, headers={"X-API-Key": "nope"})
    assert resp.status_code == 401

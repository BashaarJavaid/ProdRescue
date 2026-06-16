"""FastAPI endpoints that need no DB/broker."""
from fastapi.testclient import TestClient
from services.api import main


def test_health():
    client = TestClient(main.app)
    assert client.get("/health").json() == {"status": "ok"}


def test_metrics_exposition():
    client = TestClient(main.app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"prodrescue_active_pipelines" in resp.content

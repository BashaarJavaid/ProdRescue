"""Harness compose builder + Celery config (pure, no Docker/broker)."""
from services.api.tasks import app as celery_app
from services.mcp_servers.harness.compose import build_compose_config
from services.schemas.models import HarnessSpec


def test_build_compose_config_isolated_network():
    spec = HarnessSpec(file_path="src/x.py", env_vars={"FOO": "bar"})
    cfg = build_compose_config(spec, "abc123")
    assert cfg["networks"]["default"]["name"] == "harness_abc123"
    assert cfg["networks"]["default"]["driver"] == "bridge"
    app = cfg["services"]["app"]
    assert app["environment"] == {"FOO": "bar"}
    assert "./src:/app/src" in app["volumes"]
    assert "postgres" in cfg["services"] and "redis" in cfg["services"]


def test_celery_app_config():
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.task_serializer == "json"

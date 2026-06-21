"""Harness compose builder + Celery config (pure, no Docker/broker)."""
from services.api.tasks import app as celery_app
from services.mcp_servers.harness.compose import build_compose_config
from services.schemas.models import HarnessSpec


def test_build_compose_config_isolated_and_hardened():
    # No DB/mocked services needed → network is cut and the helper services dropped.
    spec = HarnessSpec(file_path="src/x.py", env_vars={"FOO": "bar"})
    cfg = build_compose_config(spec, "abc123")
    app = cfg["services"]["app"]
    assert app["environment"] == {"FOO": "bar"}
    assert "./src:/app/src" in app["volumes"]
    assert app["network_mode"] == "none"
    assert "postgres" not in cfg["services"] and "redis" not in cfg["services"]
    # Hardening applied to the LLM-code container.
    assert app["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in app["security_opt"]
    assert "mem_limit" in app and "pids_limit" in app


def test_build_compose_config_with_services_keeps_network():
    # A spec that needs a DB keeps postgres/redis on an isolated bridge network.
    spec = HarnessSpec(file_path="src/x.py", db_seed_sql="SELECT 1;")
    cfg = build_compose_config(spec, "abc123")
    assert cfg["networks"]["default"]["name"] == "harness_abc123"
    assert "postgres" in cfg["services"] and "redis" in cfg["services"]
    assert cfg["services"]["app"].get("network_mode") is None
    assert cfg["services"]["app"]["cap_drop"] == ["ALL"]  # still hardened


def test_celery_app_config():
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.task_serializer == "json"

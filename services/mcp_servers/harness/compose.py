"""Build a docker-compose config dict from a HarnessSpec.

The app service builds from the target's Dockerfile (for deps) but mounts the
source/tests live, so a patch applied to the stack dir is visible inside the
container without a rebuild. Each stack gets its own bridge network for
isolation (no cross-contamination between concurrent incidents).
"""
from __future__ import annotations

from services.config import settings
from services.schemas.models import HarnessSpec


def build_compose_config(spec: HarnessSpec, stack_id: str) -> dict:
    """Compose config for one isolated QA stack.

    The ``app`` container runs LLM-written code, so it is hardened: resource limits,
    all Linux caps dropped, no privilege escalation. When the spec needs no DB/mocked
    services (the common case) the app gets ``network_mode: none`` — pytest doesn't
    need the network, and cutting it kills any exfiltration / callback a hallucinated
    or poisoned patch might attempt.

    ponytail: the host docker.sock is still mounted into the harness server = host
    root. The real upgrade path is rootless DinD / a dedicated node pool / Kata. This
    in-stack hardening closes the app-container blast radius, not the daemon's.
    """
    needs_services = bool(spec.db_seed_sql) or bool(spec.mocked_services)

    app: dict = {
        "build": {"context": "."},
        "working_dir": "/app",
        "environment": spec.env_vars or {},
        "volumes": ["./src:/app/src", "./tests:/app/tests"],
        "command": "sleep infinity",
        # Hardening — applied whether or not the network is isolated.
        "mem_limit": settings.harness_mem_limit,
        "cpus": settings.harness_cpus,
        "pids_limit": settings.harness_pids_limit,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
    }

    cfg: dict = {"services": {"app": app}}

    if needs_services:
        app["depends_on"] = ["postgres", "redis"]
        cfg["services"]["postgres"] = {
            "image": "timescale/timescaledb-ha:pg15",
            "environment": {"POSTGRES_PASSWORD": "test", "POSTGRES_DB": "testdb"},
        }
        cfg["services"]["redis"] = {"image": "redis:7-alpine"}
        cfg["networks"] = {"default": {"name": f"harness_{stack_id}", "driver": "bridge"}}
    else:
        app["network_mode"] = "none"

    return cfg

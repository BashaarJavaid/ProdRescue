"""Build a docker-compose config dict from a HarnessSpec.

The app service builds from the target's Dockerfile (for deps) but mounts the
source/tests live, so a patch applied to the stack dir is visible inside the
container without a rebuild. Each stack gets its own bridge network for
isolation (no cross-contamination between concurrent incidents).
"""
from __future__ import annotations

from services.schemas.models import HarnessSpec


def build_compose_config(spec: HarnessSpec, stack_id: str) -> dict:
    network = f"harness_{stack_id}"
    return {
        "services": {
            "app": {
                "build": {"context": "."},
                "working_dir": "/app",
                "environment": spec.env_vars or {},
                "depends_on": ["postgres", "redis"],
                "volumes": ["./src:/app/src", "./tests:/app/tests"],
                "command": "sleep infinity",
            },
            "postgres": {
                "image": "timescale/timescaledb-ha:pg15",
                "environment": {
                    "POSTGRES_PASSWORD": "test",
                    "POSTGRES_DB": "testdb",
                },
            },
            "redis": {"image": "redis:7-alpine"},
        },
        "networks": {"default": {"name": network, "driver": "bridge"}},
    }

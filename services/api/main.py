"""FastAPI ingestion layer.

POST /ingest      → validate, embed+store, enqueue the agent pipeline
GET  /tasks/{id}  → poll pipeline status
GET  /health      → liveness/readiness
GET  /metrics     → Prometheus exposition
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from services.api import metrics as _metrics  # noqa: F401  (register metrics)
from services.api.database import db
from services.api.embeddings import embed_and_store
from services.config import settings
from services.logging_setup import setup_logging
from services.schemas.models import ErrorLog

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await db.close()


app = FastAPI(title="ProdRescue API", lifespan=lifespan)


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Gate /ingest on a shared secret. Empty key = unauthenticated (local demo)."""
    if not settings.ingest_api_key:
        logger.warning("INGEST_API_KEY is not set — /ingest is unauthenticated")
        return
    if x_api_key != settings.ingest_api_key:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


@app.get("/health")
async def health() -> dict:
    """Liveness — static, no dependencies (k8s livenessProbe)."""
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> JSONResponse:
    """Readiness — verify the deps /ingest needs (k8s readinessProbe)."""
    checks: dict[str, str] = {}
    try:
        await db.fetchval("SELECT 1")
        checks["db"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["db"] = f"error: {exc}"
    try:
        from kombu import Connection

        with Connection(settings.rabbitmq_url) as conn:
            conn.ensure_connection(max_retries=1, timeout=2)
        checks["broker"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["broker"] = f"error: {exc}"

    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(checks, status_code=200 if ok else 503)


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/ingest", status_code=202, dependencies=[Depends(require_api_key)])
async def ingest(log: ErrorLog) -> dict:
    """Entry point for any external error reporter (Sentry/Datadog/log shipper)."""
    from services.api.ratelimit import (
        acquire_slot,
        claim_incident,
        release_slot,
        set_incident_value,
    )

    if not await acquire_slot():
        raise HTTPException(status_code=429, detail="too many active pipelines; retry later")

    existing = await claim_incident(log.service, log.message)
    if existing is not None:
        await release_slot()  # this request won't run a pipeline; give the slot back
        return {"status": "deduplicated", **(json.loads(existing) if existing else {})}

    try:
        log_id = await embed_and_store(log)
        # Import here so the API process doesn't pull in agent/LLM deps at boot.
        from services.api.tasks import run_agent_pipeline

        task = run_agent_pipeline.delay({**log.model_dump(mode="json"), "log_id": str(log_id)})
    except Exception:
        await release_slot()  # the worker won't, since nothing was enqueued
        raise

    set_value = json.dumps({"task_id": task.id, "log_id": str(log_id)})
    await set_incident_value(log.service, log.message, set_value)
    return {"task_id": task.id, "log_id": str(log_id), "status": "queued"}


@app.get("/tasks/{task_id}")
async def task_status(task_id: str) -> dict:
    from celery.result import AsyncResult

    result = AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }

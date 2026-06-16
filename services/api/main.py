"""FastAPI ingestion layer.

POST /ingest      → validate, embed+store, enqueue the agent pipeline
GET  /tasks/{id}  → poll pipeline status
GET  /health      → liveness/readiness
GET  /metrics     → Prometheus exposition
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from services.api import metrics as _metrics  # noqa: F401  (register metrics)
from services.api.database import db
from services.api.embeddings import embed_and_store
from services.schemas.models import ErrorLog


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await db.close()


app = FastAPI(title="ProdRescue API", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/ingest", status_code=202)
async def ingest(log: ErrorLog) -> dict:
    """Entry point for any external error reporter (Sentry/Datadog/log shipper)."""
    log_id = await embed_and_store(log)

    # Import here so the API process doesn't pull in agent/LLM deps at boot.
    from services.api.tasks import run_agent_pipeline

    task = run_agent_pipeline.delay({**log.model_dump(mode="json"), "log_id": str(log_id)})
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

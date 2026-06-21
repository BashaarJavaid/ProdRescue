"""Celery worker — runs the full LangGraph agent pipeline per incident.

The worker also starts a Prometheus HTTP server (one per worker process) so the
pipeline metrics emitted from agent nodes are scrapeable.
"""
from __future__ import annotations

import asyncio

from celery import Celery
from celery.signals import worker_process_init

from services.config import settings

app = Celery(
    "prodrescue",
    broker=settings.rabbitmq_url,
    backend=settings.redis_url,
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,            # re-queue if a worker dies mid-run
    worker_prefetch_multiplier=1,   # one heavy agent task per worker at a time
    result_expires=3600,
)


@worker_process_init.connect
def _start_metrics_server(**_kwargs) -> None:
    from prometheus_client import start_http_server

    from services.logging_setup import setup_logging

    setup_logging()
    try:
        start_http_server(settings.worker_metrics_port)
    except OSError:
        # Port already bound (e.g. multiple processes sharing a port) — ignore.
        pass


@app.task(bind=True, max_retries=0, name="run_agent_pipeline")
def run_agent_pipeline(self, log_payload: dict) -> dict:
    """Runs the LangGraph pipeline synchronously inside the worker."""
    from services.agents.graph import run_graph

    return asyncio.run(run_graph(log_payload))

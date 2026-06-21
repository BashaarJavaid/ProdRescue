"""Prometheus instrumentation (spec §11.1).

Metrics live in the default registry. The API exposes them at GET /metrics; the
Celery worker starts a `prometheus_client` HTTP server (see tasks.py) so the
agent pipeline's metrics are scraped independently of the API.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from services.schemas.models import HarnessResult

PATCHES_TOTAL = Counter(
    "prodrescue_patches_total",
    "Total patches generated",
    ["service", "outcome"],  # outcome: pass | fail | max_retry
)

HARNESS_DURATION = Histogram(
    "prodrescue_harness_duration_seconds",
    "Harness execution wall time",
    buckets=[5, 15, 30, 60, 120, 300],
)

RETRY_COUNT = Histogram(
    "prodrescue_retry_count",
    "Agent loop retries per incident",
    buckets=[0, 1, 2, 3],
)

TIME_TO_PR = Histogram(
    "prodrescue_time_to_pr_seconds",
    "Wall time from ingest to PR opened",
    buckets=[30, 60, 120, 240, 480, 900],
)

COVERAGE_DELTA = Histogram(
    "prodrescue_coverage_delta",
    "Coverage delta from harness run",
    buckets=[-5, -2, -1, 0, 1, 2, 5, 10],
)

ACTIVE_PIPELINES = Gauge(
    "prodrescue_active_pipelines",
    "Currently running agent pipelines",
)

PIPELINE_FAILURES = Counter(
    "prodrescue_pipeline_failures_total",
    "Pipelines that ended without a PR",
    ["service", "reason"],  # reason: exception | gave_up
)


def emit_prometheus_metrics(
    result: HarnessResult, service: str, time_to_pr: float | None = None
) -> None:
    outcome = (
        "pass"
        if result.passed
        else ("max_retry" if result.retry_attempt >= 3 else "fail")
    )
    PATCHES_TOTAL.labels(service=service, outcome=outcome).inc()
    HARNESS_DURATION.observe(result.duration_ms / 1000)
    RETRY_COUNT.observe(result.retry_attempt)
    COVERAGE_DELTA.observe(result.coverage_delta)
    if time_to_pr is not None:
        TIME_TO_PR.observe(time_to_pr)

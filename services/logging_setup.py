"""Structured JSON logging with a per-incident correlation id.

OPT-IN via ``JSON_LOGS=true``. It replaces the root handler with a JSON formatter,
which fights Celery's and uvicorn's own logging (Celery redirects pool stdout/stderr
back through logging — installing a root StreamHandler there creates a feedback loop
that wedges the worker). So it stays off by default; enable it only where a real log
pipeline consumes the JSON and ``worker_redirect_stdouts`` is disabled.

``set_log_id(log_id)`` always works (cheap contextvar) so the id is available to the
formatter when enabled.

ponytail: stdlib logging + a json.dumps formatter — no structlog dependency.
"""
from __future__ import annotations

import contextvars
import json
import logging

from services.config import settings

_log_id: contextvars.ContextVar[str] = contextvars.ContextVar("log_id", default="-")


def set_log_id(log_id: str) -> None:
    _log_id.set(log_id)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "log_id": _log_id.get(),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logging(level: int = logging.INFO) -> None:
    if not settings.json_logs:
        return  # default: leave Celery/uvicorn logging alone
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

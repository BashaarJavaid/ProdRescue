"""LangSmith tracing shim.

Returns ``langsmith.traceable`` when tracing is configured, otherwise a no-op
decorator so nodes import cleanly without the dependency or API key.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from services.config import settings


def traceable(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    if settings.langsmith_api_key:
        try:
            import langsmith

            return langsmith.traceable(name=name)
        except ImportError:
            pass

    def _identity(fn: Callable[..., Any]) -> Callable[..., Any]:
        return fn

    return _identity

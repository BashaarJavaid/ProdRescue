"""LangGraph shared state.

TypedDict is ``total=False`` (keys appear as nodes produce them). Value types are
non-optional because nodes only ever write real values — a key is either absent
or holds a concrete value, never None.
"""
from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    # Input
    log: dict          # raw error payload from the Celery task
    log_id: str

    # Triage outputs
    root_cause: str
    affected_file: str
    harness_spec: dict   # HarnessSpec.model_dump()

    # Dev outputs
    patched_file: str    # full fixed source file (applied verbatim, no diff)
    patch: str           # unified diff (PR body + fallback)
    fixture: str         # conftest.py content
    explanation: str
    original_len: int    # length of the pre-patch source (for the scope guard)

    # QA outputs
    harness_result: dict  # HarnessResult.model_dump()

    # Output
    pr_url: str

    # Control / bookkeeping
    retry_count: int
    started_at: float               # epoch seconds, for time-to-PR metric
    messages: list                  # condensed conversation history

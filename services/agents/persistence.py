"""Persist HarnessResult rows to TimescaleDB."""
from __future__ import annotations

from services.api.database import db
from services.schemas.models import HarnessResult


async def store_harness_result(
    result: HarnessResult,
    log_id: str | None,
    patch_diff: str | None = None,
    pr_url: str | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO harness_results
            (run_id, log_id, passed, coverage_delta, failed_assertions,
             duration_ms, teardown_clean, retry_attempt, patch_diff, pr_url)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """,
        result.run_id,
        log_id,
        result.passed,
        result.coverage_delta,
        result.failed_assertions,
        result.duration_ms,
        result.teardown_clean,
        result.retry_attempt,
        patch_diff,
        pr_url,
    )


async def mark_resolved(log_id: str) -> None:
    await db.execute("UPDATE error_logs SET resolved = TRUE WHERE id = $1", log_id)

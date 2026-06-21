"""Ingestion guardrails backed by the Redis already present as the Celery backend.

* Concurrency cap — a shared counter (``prodrescue:active``) incremented in the API
  at enqueue time and decremented in the worker when the pipeline finishes. Sheds
  load past ``max_active_pipelines`` so a crash storm can't fan out into N parallel
  LLM runs + Docker stacks.
* Dedup — ``SET key NX EX=window`` on a hash of (service, normalized message) so two
  identical crashes within the window create one pipeline, not two.

All operations fail OPEN (allow / treat-as-new) on a Redis error: availability of the
ingest path matters more than a perfect cap, and the worst case is one extra pipeline.
"""
from __future__ import annotations

import hashlib
import logging
import re

import redis.asyncio as aioredis

from services.config import settings

logger = logging.getLogger(__name__)

_ACTIVE_KEY = "prodrescue:active"


def _client() -> aioredis.Redis:
    # ponytail: a fresh client per call — ingest is low-rate by design (that's the
    # whole point of the cap), so a connection pool singleton buys nothing.
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def acquire_slot() -> bool:
    """Increment the active counter; return False (and roll back) if over the cap."""
    try:
        r = _client()
        try:
            active = await r.incr(_ACTIVE_KEY)
            if active > settings.max_active_pipelines:
                await r.decr(_ACTIVE_KEY)
                return False
            return True
        finally:
            await r.aclose()
    except Exception:  # noqa: BLE001 — fail open: Redis down shouldn't block ingestion
        logger.warning("acquire_slot: Redis unavailable, failing open", exc_info=True)
        return True


async def release_slot() -> None:
    """Decrement the active counter. Best-effort — never raises.

    ponytail: a worker that dies before release leaks one slot. Upgrade path = TTL'd
    per-task keys + a periodic sweep. Fine while the worker runs --concurrency=1.
    """
    try:
        r = _client()
        try:
            await r.decr(_ACTIVE_KEY)
        finally:
            await r.aclose()
    except Exception:  # noqa: BLE001 — never break a pipeline on a cache error
        pass


_HEX_ADDR = re.compile(r"0x[0-9a-f]+")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def dedup_key(service: str, message: str) -> str:
    norm = _HEX_ADDR.sub("0xADDR", message.lower())
    norm = _UUID.sub("UUID", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    digest = hashlib.sha256(f"{service}:{norm}".encode()).hexdigest()
    return f"prodrescue:dedup:{digest}"


async def claim_incident(service: str, message: str) -> str | None:
    """Claim the dedup key. Returns None if newly claimed (proceed), else the stored
    value of the original incident (caller should treat as a duplicate)."""
    try:
        r = _client()
        try:
            key = dedup_key(service, message)
            claimed = await r.set(key, "", nx=True, ex=settings.dedup_window_seconds)
            if claimed:
                return None
            # Original may still be mid-flight (value not set yet) — empty string is
            # an acceptable "duplicate, ids unknown" signal.
            return await r.get(key) or ""
        finally:
            await r.aclose()
    except Exception:  # noqa: BLE001 — fail open: treat as new on Redis error
        logger.warning("claim_incident: Redis unavailable, treating as new", exc_info=True)
        return None


async def set_incident_value(service: str, message: str, value: str) -> None:
    """Record the original incident's ids under its dedup key, preserving the TTL."""
    try:
        r = _client()
        try:
            await r.set(dedup_key(service, message), value, keepttl=True)
        finally:
            await r.aclose()
    except Exception:  # noqa: BLE001
        pass

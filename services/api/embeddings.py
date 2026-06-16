"""Embedding pipeline.

Two backends, selected by ``EMBED_BACKEND``:

* ``sentence-transformers`` (default) — real local embeddings, no GPU required.
* ``hash`` — deterministic pseudo-embedding derived from a hash of the text.
  Used in tests / CI so the pipeline runs without downloading model weights.

Both produce a unit-normalised vector of ``settings.embed_dim`` floats, so
pgvector cosine distance behaves consistently across backends.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import struct
from functools import lru_cache
from uuid import UUID

from services.config import settings
from services.schemas.models import ErrorLog


def _normalise(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _hash_embed(text: str) -> list[float]:
    """Deterministic embedding: expand SHA-256 digests into ``embed_dim`` floats."""
    dim = settings.embed_dim
    out: list[float] = []
    counter = 0
    while len(out) < dim:
        digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        # 8 floats per 32-byte digest (4 bytes each)
        for i in range(0, 32, 4):
            (val,) = struct.unpack("<I", digest[i : i + 4])
            out.append((val / 0xFFFFFFFF) * 2.0 - 1.0)  # map to [-1, 1]
        counter += 1
    return _normalise(out[:dim])


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embed_model)


def embed(text: str) -> list[float]:
    """Synchronously embed a single string into ``embed_dim`` floats."""
    if settings.embed_backend == "hash":
        return _hash_embed(text)
    vec = _model().encode(text, normalize_embeddings=True)
    return [float(x) for x in vec]


async def embed_async(text: str) -> list[float]:
    """Async wrapper — runs the (CPU-bound) encoder in a worker thread."""
    return await asyncio.to_thread(embed, text)


async def embed_and_store(log: ErrorLog) -> UUID:
    """Embed the error message and insert the row into ``error_logs``."""
    from services.api.database import db

    embedding = await embed_async(log.message)
    log_id = await db.fetchval(
        """
        INSERT INTO error_logs
            (occurred_at, service, message, stacktrace, embedding, metadata)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        log.occurred_at,
        log.service,
        log.message,
        log.stacktrace,
        embedding,
        log.metadata,
    )
    return log_id

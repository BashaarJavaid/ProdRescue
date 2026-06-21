"""Provider-agnostic LLM client.

Wraps any OpenAI-compatible chat endpoint (default: Xiaomi MiMo-V2.5-Pro) with
Instructor so agent nodes get validated Pydantic objects back instead of raw
text. Swap providers by changing LLM_BASE_URL / LLM_MODEL / LLM_API_KEY only.
"""
from __future__ import annotations

from functools import lru_cache
from typing import TypeVar

from pydantic import BaseModel

from services.config import settings

T = TypeVar("T", bound=BaseModel)


@lru_cache(maxsize=1)
def get_client():
    """Instructor-wrapped async OpenAI-compatible client."""
    import instructor
    from openai import AsyncOpenAI

    base = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    return instructor.from_openai(base, mode=instructor.Mode.JSON)


async def structured(
    response_model: type[T],
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_retries: int = 2,
) -> T:
    """Single structured-output LLM call. Returns an instance of ``response_model``."""
    client = get_client()
    extra = {} if settings.llm_temperature is None else {"temperature": settings.llm_temperature}
    return await client.chat.completions.create(
        model=model or settings.llm_model,
        response_model=response_model,
        max_retries=max_retries,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        **extra,
    )

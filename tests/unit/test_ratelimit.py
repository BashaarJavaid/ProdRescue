"""Concurrency cap + dedup logic, exercised against a tiny in-memory fake Redis."""
from services.api import ratelimit
from services.config import settings


class FakeRedis:
    def __init__(self, store: dict) -> None:
        self.store = store

    async def incr(self, k):
        self.store[k] = int(self.store.get(k, 0)) + 1
        return self.store[k]

    async def decr(self, k):
        self.store[k] = int(self.store.get(k, 0)) - 1
        return self.store[k]

    async def set(self, k, v, nx=False, ex=None, keepttl=False):
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    async def get(self, k):
        return self.store.get(k)

    async def aclose(self):
        pass


def _patch(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(ratelimit, "_client", lambda: FakeRedis(store))
    return store


async def test_cap_sheds_past_limit(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(settings, "max_active_pipelines", 2)
    assert await ratelimit.acquire_slot() is True   # 1
    assert await ratelimit.acquire_slot() is True   # 2
    assert await ratelimit.acquire_slot() is False  # over cap, rolled back
    await ratelimit.release_slot()                  # back to 1 free
    assert await ratelimit.acquire_slot() is True


async def test_dedup_collapses_identical_crash(monkeypatch):
    _patch(monkeypatch)
    first = await ratelimit.claim_incident("payments", "AttributeError at 0xdeadbeef")
    assert first is None                            # newly claimed → proceed
    # Same crash, different hex address → normalized to the same key → duplicate.
    second = await ratelimit.claim_incident("payments", "AttributeError at 0xcafef00d")
    assert second is not None                       # duplicate

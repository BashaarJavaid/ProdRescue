"""Backfill historical resolved incidents so pgvector search has neighbours.

Each seed inserts a resolved error_log + a passing harness_result with a PR URL,
so both semantic_search_logs and get_similar_resolutions return useful context.

Usage:
    PYTHONPATH=. DATABASE_URL=... python scripts/seed_incidents.py
"""
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from services.api.database import db
from services.api.embeddings import embed_async

SEEDS = [
    {
        "service": "payments",
        "message": "AttributeError: 'NoneType' object has no attribute 'total' in charge()",
        "patch_diff": "--- a/src/payments/processor.py\n+++ b/src/payments/processor.py\n"
                      "@@\n-    amount = order.total * 100\n+    if order is None:\n"
                      "+        raise PaymentError('no order')\n+    amount = order.total * 100\n",
        "pr_url": "https://github.com/youruser/sample/pull/11",
    },
    {
        "service": "payments",
        "message": "KeyError: 'currency' when building charge request payload",
        "patch_diff": "--- a/src/payments/processor.py\n+++ b/src/payments/processor.py\n"
                      "@@\n-    cur = payload['currency']\n+    cur = payload.get('currency', 'USD')\n",
        "pr_url": "https://github.com/youruser/sample/pull/7",
    },
    {
        "service": "checkout",
        "message": "ConnectionError: redis timeout while reading session cache",
        "patch_diff": "--- a/src/checkout/cache.py\n+++ b/src/checkout/cache.py\n"
                      "@@\n-    return redis.get(key)\n+    return redis.get(key, timeout=2)\n",
        "pr_url": "https://github.com/youruser/sample/pull/3",
    },
    {
        "service": "auth",
        "message": "TypeError: expected str, got NoneType in decode_token()",
        "patch_diff": "--- a/src/auth/jwt.py\n+++ b/src/auth/jwt.py\n"
                      "@@\n-    return jwt.decode(token)\n+    if token is None:\n"
                      "+        raise AuthError('missing token')\n+    return jwt.decode(token)\n",
        "pr_url": "https://github.com/youruser/sample/pull/19",
    },
]


async def main() -> None:
    now = datetime.now(UTC)
    for i, seed in enumerate(SEEDS):
        embedding = await embed_async(seed["message"])
        log_id = await db.fetchval(
            """
            INSERT INTO error_logs
                (occurred_at, service, message, stacktrace, embedding, resolved, metadata)
            VALUES ($1, $2, $3, $4, $5, TRUE, '{}')
            RETURNING id
            """,
            now - timedelta(days=i + 1),
            seed["service"],
            seed["message"],
            "",
            embedding,
        )
        await db.execute(
            """
            INSERT INTO harness_results
                (run_id, log_id, passed, coverage_delta, duration_ms,
                 teardown_clean, retry_attempt, patch_diff, pr_url)
            VALUES ($1, $2, TRUE, 0.5, 2500, TRUE, 1, $3, $4)
            """,
            uuid4(),
            log_id,
            seed["patch_diff"],
            seed["pr_url"],
        )
        print(f"seeded resolved incident: {seed['service']} — {seed['message'][:50]}…")

    await db.close()
    print(f"\nSeeded {len(SEEDS)} resolved incidents with PRs.")


if __name__ == "__main__":
    asyncio.run(main())

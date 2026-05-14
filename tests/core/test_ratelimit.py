import asyncio
import time

import pytest

from inboxcleaner.core.ratelimit import RateLimited, TokenBucket, retry_on_rate_limit


@pytest.mark.asyncio
async def test_token_bucket_limits_rate():
    bucket = TokenBucket(rate_per_sec=50, capacity=50)
    start = time.monotonic()
    # 100 takes from a 50/s bucket should take ~1s
    await asyncio.gather(*(bucket.take(1) for _ in range(100)))
    elapsed = time.monotonic() - start
    assert 0.8 <= elapsed <= 2.5, f"unexpected elapsed: {elapsed}"


@pytest.mark.asyncio
async def test_retry_on_rate_limit_succeeds_after_retries():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimited()
        return "ok"

    result = await retry_on_rate_limit(flaky, max_attempts=5, base_delay=0.001)
    assert result == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_retry_gives_up_after_max_attempts():
    async def always_429():
        raise RateLimited()

    with pytest.raises(RateLimited):
        await retry_on_rate_limit(always_429, max_attempts=3, base_delay=0.001)

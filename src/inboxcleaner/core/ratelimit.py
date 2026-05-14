import asyncio
import random
import time
from collections.abc import Awaitable, Callable


class RateLimited(Exception):
    """Raised by GmailClient on HTTP 429 to trigger retry."""


class TokenBucket:
    """Simple asyncio token bucket.

    Calls to take() block until tokens are available.
    """

    def __init__(self, *, rate_per_sec: float, capacity: int) -> None:
        self._rate = rate_per_sec
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def take(self, n: int = 1) -> None:
        """Take n tokens. n may exceed capacity; the take is chunked internally."""
        remaining = n
        while remaining > 0:
            chunk = min(remaining, self._capacity)
            while True:
                async with self._lock:
                    now = time.monotonic()
                    self._tokens = min(
                        self._capacity, self._tokens + (now - self._last) * self._rate
                    )
                    self._last = now
                    if self._tokens >= chunk:
                        self._tokens -= chunk
                        break
                    deficit = chunk - self._tokens
                    wait = deficit / self._rate
                await asyncio.sleep(wait)
            remaining -= chunk


async def retry_on_rate_limit[T](
    fn: Callable[[], Awaitable[T]], *, max_attempts: int = 5, base_delay: float = 0.5
) -> T:
    last: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await fn()
        except RateLimited as exc:
            last = exc
            sleep = base_delay * (2**attempt) + random.uniform(0, base_delay)
            await asyncio.sleep(sleep)
    assert last is not None
    raise last

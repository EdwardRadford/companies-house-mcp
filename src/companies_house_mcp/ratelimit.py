"""Client-side rate limiting.

Companies House allows 600 requests per rolling 5 minutes per key and answers
the 601st with a 429 that locks the key out until the window moves on. An
agent that fans out (profile, officers, filings and charges for twenty
search hits) can hit that in seconds. So the limiter does two things:

* keeps a rolling window of our own request times and waits for a slot when
  the wait is short, which smooths bursts without the model noticing;
* refuses immediately, with the real wait time, when the wait would be long,
  because a tool call that silently hangs for four minutes is worse for an
  agent than an error saying "try again in 240 seconds".

It also defers to the server: if a response says the key is exhausted
(X-Ratelimit-Remain: 0), the limiter blocks until X-Ratelimit-Reset,
which covers other processes sharing the same key.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable

import anyio

from .errors import RateLimited

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class SlidingWindowLimiter:
    def __init__(
        self,
        max_requests: int = 600,
        window_seconds: float = 300.0,
        max_wait_seconds: float = 5.0,
        *,
        clock: Clock = time.monotonic,
        wall_clock: Clock = time.time,
        sleep: Sleep = anyio.sleep,
    ) -> None:
        if max_requests < 1 or window_seconds <= 0:
            raise ValueError("max_requests must be >= 1 and window_seconds > 0")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_wait_seconds = max_wait_seconds
        self._clock = clock
        self._wall_clock = wall_clock
        self._sleep = sleep
        self._sent: deque[float] = deque()
        self._blocked_until = 0.0
        self._lock = anyio.Lock()

    def _wait_needed(self, now: float) -> float:
        while self._sent and now - self._sent[0] >= self.window_seconds:
            self._sent.popleft()
        wait = max(0.0, self._blocked_until - now)
        if len(self._sent) >= self.max_requests:
            wait = max(wait, self._sent[0] + self.window_seconds - now)
        return wait

    async def acquire(self) -> None:
        """Take a slot, waiting up to max_wait_seconds, else raise RateLimited."""
        async with self._lock:
            wait = self._wait_needed(self._clock())
            if wait > self.max_wait_seconds:
                raise RateLimited(wait)
            if wait > 0:
                await self._sleep(wait)
                self._wait_needed(self._clock())
            self._sent.append(self._clock())

    def observe(self, remaining: str | None, reset_epoch: str | None) -> None:
        """Feed the server's X-Ratelimit-Remain / X-Ratelimit-Reset headers back in."""
        if remaining is None or reset_epoch is None:
            return
        try:
            left = int(remaining)
            reset = float(reset_epoch)
        except ValueError:
            return
        if left <= 0:
            self.block_for(reset - self._wall_clock())

    def block_for(self, seconds: float) -> None:
        """Refuse all requests for `seconds` (e.g. after a 429)."""
        if seconds > 0:
            self._blocked_until = max(self._blocked_until, self._clock() + seconds)

    def seconds_until_reset(self, reset_epoch: str | None, default: float) -> float:
        try:
            return max(1.0, float(reset_epoch) - self._wall_clock()) if reset_epoch else default
        except ValueError:
            return default

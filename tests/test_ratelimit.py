import pytest

from companies_house_mcp.errors import RateLimited
from companies_house_mcp.ratelimit import SlidingWindowLimiter

pytestmark = pytest.mark.anyio


class FakeTime:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def wall(self) -> float:
        return 1_700_000_000.0 + self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def limiter(t: FakeTime, **kw: float) -> SlidingWindowLimiter:
    return SlidingWindowLimiter(clock=t.clock, wall_clock=t.wall, sleep=t.sleep, **kw)  # type: ignore[arg-type]


async def test_allows_up_to_the_limit_without_waiting() -> None:
    t = FakeTime()
    lim = limiter(t, max_requests=3, window_seconds=10)
    for _ in range(3):
        await lim.acquire()
    assert t.slept == []


async def test_short_wait_is_absorbed() -> None:
    t = FakeTime()
    lim = limiter(t, max_requests=2, window_seconds=10, max_wait_seconds=5)
    await lim.acquire()
    t.now += 7
    await lim.acquire()
    await lim.acquire()  # first slot frees at +10, i.e. 3s from now
    assert t.slept == [pytest.approx(3)]


async def test_long_wait_is_refused_with_the_real_wait() -> None:
    t = FakeTime()
    lim = limiter(t, max_requests=2, window_seconds=300, max_wait_seconds=5)
    await lim.acquire()
    await lim.acquire()
    with pytest.raises(RateLimited) as err:
        await lim.acquire()
    assert err.value.retry_after_seconds == 300
    assert t.slept == [], "must not hang the tool call"


async def test_window_slides() -> None:
    t = FakeTime()
    lim = limiter(t, max_requests=1, window_seconds=10, max_wait_seconds=0)
    await lim.acquire()
    t.now += 10
    await lim.acquire()


async def test_server_exhaustion_header_blocks_until_reset() -> None:
    t = FakeTime()
    lim = limiter(t, max_requests=600, window_seconds=300, max_wait_seconds=5)
    lim.observe(remaining="0", reset_epoch=str(t.wall() + 120))
    with pytest.raises(RateLimited) as err:
        await lim.acquire()
    assert err.value.retry_after_seconds == 120
    t.now += 121
    await lim.acquire()


async def test_ignores_absent_or_garbled_headers() -> None:
    t = FakeTime()
    lim = limiter(t)
    lim.observe(None, None)
    lim.observe("lots", "soon")
    lim.observe("12", str(t.wall() + 999))
    await lim.acquire()


def test_rejects_nonsense_configuration() -> None:
    with pytest.raises(ValueError):
        SlidingWindowLimiter(max_requests=0)

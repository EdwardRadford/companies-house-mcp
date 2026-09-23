"""Transport behaviour: every way a request can go, and what the caller gets."""

import base64

import httpx
import pytest

from companies_house_mcp.errors import (
    AuthenticationFailed,
    BadRequest,
    CompanyNotFound,
    NotConfigured,
    RateLimited,
    UpstreamUnavailable,
)
from companies_house_mcp.ratelimit import SlidingWindowLimiter

from .conftest import FakeCompaniesHouse, Reply, make_client

pytestmark = pytest.mark.anyio

PROFILE = "/company/09446231"


async def test_sends_key_as_basic_auth_username(ch: FakeCompaniesHouse) -> None:
    async with make_client(ch, api_key="s3cret") as c:
        await c.company_profile("09446231")
    auth = ch.requests[0].headers["authorization"]
    assert auth == "Basic " + base64.b64encode(b"s3cret:").decode()
    assert ch.requests[0].headers["user-agent"].startswith("companies-house-mcp/")


async def test_no_key_fails_before_any_request(ch: FakeCompaniesHouse) -> None:
    async with make_client(ch, api_key=None) as c:
        with pytest.raises(NotConfigured):
            await c.company_profile("09446231")
    assert ch.requests == []


async def test_missing_company_is_not_found(ch: FakeCompaniesHouse) -> None:
    async with make_client(ch) as c:
        with pytest.raises(CompanyNotFound) as err:
            await c.company_profile("01234567")
    assert err.value.company_number == "01234567"


async def test_empty_list_for_real_company_is_confirmed_then_returned(ch: FakeCompaniesHouse) -> None:
    async with make_client(ch) as c:
        charges = await c.charges("SC654321", 25, 0)
    assert charges["items"] == []
    assert ch.calls_to("/company/SC654321") == 1, "must confirm the company exists"


@pytest.mark.parametrize("resource", ["officers", "filing_history", "charges", "persons_with_significant_control"])
async def test_empty_list_for_missing_company_is_not_found(ch: FakeCompaniesHouse, resource: str) -> None:
    # Live behaviour: /company/00000001/charges is 200 with no items although 00000001 does not exist.
    async with make_client(ch) as c:
        with pytest.raises(CompanyNotFound):
            await getattr(c, resource)("01234567", 25, 0)


async def test_404_on_a_list_gets_the_same_check(ch: FakeCompaniesHouse) -> None:
    ch.on("/company/SC654321/charges", Reply(404))
    ch.on("/company/01234567/charges", Reply(404))
    async with make_client(ch) as c:
        assert (await c.charges("SC654321", 25, 0))["items"] == []
        with pytest.raises(CompanyNotFound):
            await c.charges("01234567", 25, 0)


async def test_non_empty_list_costs_one_request(ch: FakeCompaniesHouse) -> None:
    async with make_client(ch) as c:
        await c.officers("09446231", 35, 0)
    assert len(ch.requests) == 1


async def test_empty_later_page_is_not_rechecked(ch: FakeCompaniesHouse) -> None:
    async with make_client(ch) as c:
        await c.officers("01234567", 35, 100)
    assert len(ch.requests) == 1


async def test_429_raises_with_reset_and_blocks_locally(ch: FakeCompaniesHouse) -> None:
    import time

    reset = str(int(time.time()) + 90)
    ch.on(PROFILE, Reply(429, {"error": "rate limited"}, {"X-Ratelimit-Reset": reset, "X-Ratelimit-Remain": "0"}))
    async with make_client(ch, limiter=SlidingWindowLimiter(max_wait_seconds=5)) as c:
        with pytest.raises(RateLimited) as err:
            await c.company_profile("09446231")
        assert 80 <= err.value.retry_after_seconds <= 91
        with pytest.raises(RateLimited):
            await c.company_profile("09446231")
    assert ch.calls_to(PROFILE) == 1, "second call must be refused without touching the API"


async def test_exhaustion_header_on_success_blocks_the_next_call(ch: FakeCompaniesHouse) -> None:
    import time

    # The live header is X-Ratelimit-Remain (checked 23 Sep 2026), not X-Ratelimit-Remaining.
    headers = {"X-Ratelimit-Remain": "0", "X-Ratelimit-Reset": str(int(time.time()) + 200)}
    ch.on(PROFILE, Reply(200, {"company_number": "09446231", "company_name": "X"}, headers))
    async with make_client(ch, limiter=SlidingWindowLimiter(max_wait_seconds=5)) as c:
        await c.company_profile("09446231")
        with pytest.raises(RateLimited):
            await c.company_profile("09446231")


async def test_transient_5xx_is_retried_once(ch: FakeCompaniesHouse) -> None:
    ch.on(PROFILE, Reply(503), Reply(200, {"company_number": "09446231"}))
    async with make_client(ch) as c:
        assert (await c.company_profile("09446231"))["company_number"] == "09446231"
    assert ch.calls_to(PROFILE) == 2


async def test_persistent_5xx_gives_up(ch: FakeCompaniesHouse) -> None:
    ch.on(PROFILE, Reply(502))
    async with make_client(ch) as c:
        with pytest.raises(UpstreamUnavailable) as err:
            await c.company_profile("09446231")
    assert "HTTP 502" in str(err.value)
    assert ch.calls_to(PROFILE) == 2


async def test_500_is_not_retried(ch: FakeCompaniesHouse) -> None:
    ch.on(PROFILE, Reply(500))
    async with make_client(ch) as c:
        with pytest.raises(UpstreamUnavailable):
            await c.company_profile("09446231")
    assert ch.calls_to(PROFILE) == 1


async def test_timeout_is_upstream_unavailable(ch: FakeCompaniesHouse) -> None:
    ch.on(PROFILE, Reply(raise_exc=httpx.ReadTimeout("slow")))
    async with make_client(ch, timeout_seconds=3) as c:
        with pytest.raises(UpstreamUnavailable) as err:
            await c.company_profile("09446231")
    assert "3 seconds" in str(err.value)


async def test_connection_failure_is_upstream_unavailable(ch: FakeCompaniesHouse) -> None:
    ch.on(PROFILE, Reply(raise_exc=httpx.ConnectError("dns")))
    async with make_client(ch) as c:
        with pytest.raises(UpstreamUnavailable) as err:
            await c.company_profile("09446231")
    assert "ConnectError" in str(err.value)


async def test_html_error_page_with_200_is_upstream_unavailable(ch: FakeCompaniesHouse) -> None:
    ch.on(PROFILE, Reply(200, raw_text="<html>Service unavailable</html>"))
    async with make_client(ch) as c:
        with pytest.raises(UpstreamUnavailable):
            await c.company_profile("09446231")


async def test_401_is_authentication_failed(ch: FakeCompaniesHouse) -> None:
    ch.on(PROFILE, Reply(401, {"error": "Invalid Authorization"}))
    async with make_client(ch) as c:
        with pytest.raises(AuthenticationFailed):
            await c.company_profile("09446231")


async def test_400_carries_upstream_detail(ch: FakeCompaniesHouse) -> None:
    ch.on("/search/companies", Reply(400, {"errors": [{"error": "items-per-page-too-large", "type": "ch:validation"}]}))
    async with make_client(ch) as c:
        with pytest.raises(BadRequest) as err:
            await c.search_companies("x", 500, 0)
    assert "items-per-page-too-large" in str(err.value)


async def test_passes_paging_and_category_params(ch: FakeCompaniesHouse) -> None:
    async with make_client(ch) as c:
        await c.filing_history("09446231", 10, 20, "address")
    params = ch.requests[0].url.params
    assert (params["items_per_page"], params["start_index"], params["category"]) == ("10", "20", "address")

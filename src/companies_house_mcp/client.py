"""Thin async client for the Companies House public data API.

It returns the API's JSON unchanged; shaping for the model happens in
`shaping.py`. Its job is the transport: auth, rate limiting, one retry on
transient failures, and turning every HTTP outcome into either data or one of
the errors in `errors.py`.
"""

from __future__ import annotations

from typing import Any

import anyio
import httpx

from . import __version__
from .errors import (
    AuthenticationFailed,
    BadRequest,
    CompaniesHouseError,
    CompanyNotFound,
    NotConfigured,
    RateLimited,
    UpstreamUnavailable,
)
from .ratelimit import Sleep, SlidingWindowLimiter

DEFAULT_BASE_URL = "https://api.company-information.service.gov.uk"
_RETRYABLE_STATUS = {502, 503, 504}

JSON = dict[str, Any]


class _Missing(Exception):
    """A 404 from upstream. Callers decide what it means for their resource."""


class CompaniesHouseClient:
    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 10.0,
        limiter: SlidingWindowLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        retries: int = 1,
        retry_backoff_seconds: float = 0.5,
        sleep: Sleep = anyio.sleep,
    ) -> None:
        self._configured = bool(api_key)
        self._limiter = limiter or SlidingWindowLimiter()
        self._retries = retries
        self._backoff = retry_backoff_seconds
        self._sleep = sleep
        self._timeout_seconds = timeout_seconds
        self._http = httpx.AsyncClient(
            base_url=base_url,
            auth=httpx.BasicAuth(api_key or "", ""),
            timeout=timeout_seconds,
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": f"companies-house-mcp/{__version__}"},
        )

    async def __aenter__(self) -> CompaniesHouseClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- endpoints ---------------------------------------------------------

    async def search_companies(self, query: str, items_per_page: int, start_index: int) -> JSON:
        params = {"q": query, "items_per_page": items_per_page, "start_index": start_index}
        try:
            return await self._get("/search/companies", params)
        except _Missing:
            return {"items": [], "total_results": 0, "start_index": start_index}

    async def company_profile(self, company_number: str) -> JSON:
        try:
            return await self._get(f"/company/{company_number}")
        except _Missing:
            raise CompanyNotFound(company_number) from None

    async def officers(self, company_number: str, items_per_page: int, start_index: int) -> JSON:
        params = {"items_per_page": items_per_page, "start_index": start_index, "order_by": "appointed_on"}
        return await self._company_list(company_number, "officers", params)

    async def filing_history(
        self, company_number: str, items_per_page: int, start_index: int, category: str | None = None
    ) -> JSON:
        params: dict[str, Any] = {"items_per_page": items_per_page, "start_index": start_index}
        if category:
            params["category"] = category
        return await self._company_list(company_number, "filing-history", params)

    async def charges(self, company_number: str, items_per_page: int, start_index: int) -> JSON:
        params = {"items_per_page": items_per_page, "start_index": start_index}
        return await self._company_list(company_number, "charges", params)

    async def persons_with_significant_control(
        self, company_number: str, items_per_page: int, start_index: int
    ) -> JSON:
        params = {"items_per_page": items_per_page, "start_index": start_index}
        return await self._company_list(company_number, "persons-with-significant-control", params)

    async def registered_office_address(self, company_number: str) -> JSON:
        try:
            return await self._get(f"/company/{company_number}/registered-office-address")
        except _Missing:
            raise CompanyNotFound(company_number) from None

    # -- plumbing ----------------------------------------------------------

    async def _company_list(self, company_number: str, resource: str, params: dict[str, Any]) -> JSON:
        """GET a list under a company.

        Companies House can answer 404 both for "no such company" and for
        "this company has none of these" (a list resource that was never
        created, such as charges for a company that never registered one). Those mean very different things to a
        model, so on a 404 we ask for the profile: if the company exists the
        list is genuinely empty, otherwise the profile call raises
        CompanyNotFound.
        """
        try:
            return await self._get(f"/company/{company_number}/{resource}", params)
        except _Missing:
            await self.company_profile(company_number)
            return {"items": [], "total_results": 0, "total_count": 0, "start_index": params.get("start_index", 0)}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> JSON:
        if not self._configured:
            raise NotConfigured()
        attempt = 0
        while True:
            await self._limiter.acquire()
            try:
                response = await self._http.get(path, params=params)
            except httpx.TimeoutException:
                failure: CompaniesHouseError = UpstreamUnavailable(
                    f"no response within {self._timeout_seconds:g} seconds"
                )
            except httpx.TransportError as exc:
                failure = UpstreamUnavailable(f"connection failed: {type(exc).__name__}")
            else:
                self._limiter.observe(
                    response.headers.get("X-Ratelimit-Remaining"), response.headers.get("X-Ratelimit-Reset")
                )
                if response.status_code not in _RETRYABLE_STATUS:
                    return self._handle(response)
                failure = UpstreamUnavailable(f"HTTP {response.status_code}")
            if attempt >= self._retries:
                raise failure
            attempt += 1
            await self._sleep(self._backoff * attempt)

    def _handle(self, response: httpx.Response) -> JSON:
        status = response.status_code
        if status == 200:
            try:
                body = response.json()
            except ValueError:
                raise UpstreamUnavailable("HTTP 200 with a body that is not JSON") from None
            if not isinstance(body, dict):
                raise UpstreamUnavailable("HTTP 200 with an unexpected JSON shape")
            return body
        if status == 404:
            raise _Missing()
        if status == 401:
            raise AuthenticationFailed()
        if status == 429:
            wait = self._limiter.seconds_until_reset(response.headers.get("X-Ratelimit-Reset"), default=60.0)
            self._limiter.block_for(wait)
            raise RateLimited(wait)
        if status >= 500:
            raise UpstreamUnavailable(f"HTTP {status}")
        raise BadRequest(f"HTTP {status}: {_error_detail(response)}")


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or "no detail given"
    errors = body.get("errors") if isinstance(body, dict) else None
    if isinstance(errors, list) and errors:
        return "; ".join(str(e.get("error", e)) if isinstance(e, dict) else str(e) for e in errors)[:300]
    return str(body)[:300]

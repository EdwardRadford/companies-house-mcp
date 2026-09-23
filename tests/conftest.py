"""Shared test harness.

`FakeCompaniesHouse` stands in for the API at the HTTP layer (httpx's
MockTransport), so the real client, limiter, retry and error mapping all run
in every test. Tool tests go one step further and talk to the server through
an in-process MCP client, the same path a real host takes.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import Client

from companies_house_mcp.client import CompaniesHouseClient
from companies_house_mcp.ratelimit import SlidingWindowLimiter
from companies_house_mcp.server import build_server

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@dataclass
class Reply:
    status: int = 200
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    raise_exc: Exception | None = None
    raw_text: str | None = None


@dataclass
class _Route:
    path: str
    params: dict[str, str]
    replies: list[Reply]
    calls: int = 0


class FakeCompaniesHouse:
    """Routes by path (and optionally query params). Unknown paths get a 404, as upstream does."""

    def __init__(self) -> None:
        self._routes: list[_Route] = []
        self.requests: list[httpx.Request] = []

    def on(self, path: str, *replies: Reply, **params: str) -> None:
        self._routes.insert(0, _Route(path, params, list(replies) or [Reply()]))

    def fixture(self, path: str, name: str, **params: str) -> None:
        self.on(path, Reply(body=load(name)), **params)

    def calls_to(self, path: str) -> int:
        return sum(1 for r in self.requests if r.url.path == path)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for route in self._routes:
            if route.path == request.url.path and all(request.url.params.get(k) == v for k, v in route.params.items()):
                reply = route.replies[min(route.calls, len(route.replies) - 1)]
                route.calls += 1
                if reply.raise_exc:
                    raise reply.raise_exc
                if reply.raw_text is not None:
                    return httpx.Response(reply.status, text=reply.raw_text, headers=reply.headers)
                return httpx.Response(reply.status, json=reply.body, headers=reply.headers)
        return httpx.Response(404, json={"errors": [{"error": "not-found", "type": "ch:service"}]})


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def ch() -> FakeCompaniesHouse:
    fake = FakeCompaniesHouse()
    fake.fixture("/search/companies", "search_halcyon.json", q="Halcyon Forge")
    fake.fixture("/search/companies", "search_empty.json", q="zzqx nothing")
    fake.fixture("/company/09446231", "profile_09446231.json")
    fake.fixture("/company/SC654321", "profile_SC654321.json")
    fake.fixture("/company/09446231/officers", "officers_09446231.json")
    fake.fixture("/company/09446231/filing-history", "filings_09446231.json")
    fake.fixture("/company/09446231/filing-history", "filings_address_09446231.json", category="address")
    fake.fixture("/company/09446231/charges", "charges_09446231.json")
    fake.fixture("/company/09446231/registered-office-address", "roa_09446231.json")
    fake.fixture("/company/09446231/persons-with-significant-control", "psc_09446231.json")
    return fake


def make_client(ch: FakeCompaniesHouse, **kwargs: Any) -> CompaniesHouseClient:
    kwargs.setdefault("limiter", SlidingWindowLimiter(sleep=_no_sleep))
    kwargs.setdefault("sleep", _no_sleep)
    return CompaniesHouseClient(kwargs.pop("api_key", "test-key"), transport=httpx.MockTransport(ch.handler), **kwargs)


@pytest.fixture
async def client(ch: FakeCompaniesHouse) -> AsyncIterator[CompaniesHouseClient]:
    async with make_client(ch) as c:
        yield c


@pytest.fixture
async def session(client: CompaniesHouseClient) -> AsyncIterator[Client]:
    async with Client(build_server(client)) as c:
        yield c


async def call(session: Client, tool: str, **arguments: Any) -> dict[str, Any]:
    """Call a tool and return its structured result, failing the test on a tool error."""
    result = await session.call_tool(tool, arguments)
    assert not result.is_error, result.content[0].text  # type: ignore[union-attr]
    assert result.structured_content is not None
    return result.structured_content


async def call_error(session: Client, tool: str, **arguments: Any) -> str:
    """Call a tool that should fail and return the message the model would see."""
    result = await session.call_tool(tool, arguments)
    assert result.is_error, f"expected an error, got {result.structured_content}"
    return result.content[0].text  # type: ignore[union-attr]

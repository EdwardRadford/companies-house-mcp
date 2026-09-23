"""The server as a host launches it: a real subprocess speaking MCP over stdio.

Catches what in-process tests cannot: the entry point, packaging of the
enumeration data, and anything that writes to stdout and corrupts the
protocol stream.
"""

import os
import sys

import pytest
from mcp import Client, StdioServerParameters

pytestmark = pytest.mark.anyio


async def test_runs_over_stdio_without_a_key() -> None:
    env = {k: v for k, v in os.environ.items() if k != "COMPANIES_HOUSE_API_KEY"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "companies_house_mcp"], env=env)
    async with Client(params) as session:
        tools = (await session.list_tools()).tools
        assert len(tools) == 7
        result = await session.call_tool("get_company_profile", {"company_number": "00445790"})
        assert result.is_error
        assert "COMPANIES_HOUSE_API_KEY" in result.content[0].text  # type: ignore[union-attr]

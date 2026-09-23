"""Guards on the tool surface itself: the contract a host and a model rely on."""

import json

import pytest
from mcp import Client

pytestmark = pytest.mark.anyio

EXPECTED_TOOLS = {
    "search_companies",
    "get_company_profile",
    "list_officers",
    "list_filings",
    "list_charges",
    "get_registered_office_history",
    "list_persons_with_significant_control",
}

# What a host puts in the model's context for every conversation: names,
# descriptions and input schemas. Growing it should be a decision, not drift.
CONTEXT_BUDGET_CHARS = 12_000


async def test_exactly_the_intended_tools(session: Client) -> None:
    tools = (await session.list_tools()).tools
    assert {t.name for t in tools} == EXPECTED_TOOLS


async def test_every_tool_is_declared_read_only(session: Client) -> None:
    for tool in (await session.list_tools()).tools:
        a = tool.annotations
        assert a is not None, tool.name
        assert a.read_only_hint is True, tool.name
        assert a.destructive_hint is False, tool.name
        assert a.idempotent_hint is True, tool.name
        assert a.open_world_hint is True, tool.name
        assert a.title, tool.name


async def test_every_tool_has_typed_output_and_documented_inputs(session: Client) -> None:
    for tool in (await session.list_tools()).tools:
        assert tool.output_schema, f"{tool.name} has no output schema"
        assert tool.description and len(tool.description) > 80, tool.name
        for name, prop in tool.input_schema["properties"].items():
            assert prop.get("description"), f"{tool.name}.{name} has no description"


async def test_paging_limits_are_bounded(session: Client) -> None:
    for tool in (await session.list_tools()).tools:
        props = tool.input_schema["properties"]
        if "limit" in props:
            assert props["limit"]["maximum"] <= 100, tool.name
            assert props["limit"]["minimum"] >= 1, tool.name


async def test_tool_surface_fits_its_context_budget(session: Client) -> None:
    tools = (await session.list_tools()).tools
    size = sum(len(t.name) + len(t.description or "") + len(json.dumps(t.input_schema)) for t in tools)
    assert size <= CONTEXT_BUDGET_CHARS, f"tool surface is {size} chars"


async def test_server_identifies_itself_and_explains_usage(session: Client) -> None:
    assert session.server_info is not None
    assert session.server_info.name == "companies-house"
    assert session.instructions and "search_companies" in session.instructions

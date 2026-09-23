"""The MCP server: seven read-only tools over the Companies House register.

Tool descriptions are the model's only documentation, so each one says when
to use the tool, what it will not do, and which tool to call next. Argument
schemas carry hard limits (page sizes, enums) so a bad call is rejected by
validation before it costs an upstream request.
"""

import argparse
import os
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__, shaping
from .client import DEFAULT_BASE_URL, CompaniesHouseClient
from .company_number import normalise_company_number
from .errors import CompaniesHouseError
from .models import (
    ChargeList,
    CompanyProfile,
    CompanySearchResult,
    FilingList,
    OfficerList,
    PscList,
    RegisteredOfficeHistory,
)

INSTRUCTIONS = """\
Read-only access to the UK Companies House register: every company registered in
England, Wales, Scotland and Northern Ireland, live and dissolved.

Start with search_companies when you have a name, then use the company_number it
returns with the other tools. get_company_profile is the cheapest overview and its
`warnings` field flags overdue filings, insolvency and strike-off action. Only call
the list tools for the detail a question needs; each call counts against a shared
limit of 600 requests per 5 minutes.

The register is what companies have filed. It is authoritative for what was filed
and when, not proof that what was filed is true.
"""

CompanyNumber = Annotated[
    str,
    Field(
        description=(
            "Companies House company number, e.g. 00445790 or SC123456. Spaces and missing "
            "leading zeros are fine. Get it from search_companies if you only have a name."
        ),
        min_length=1,
        max_length=24,
    ),
]
StartIndex = Annotated[
    int, Field(ge=0, le=10_000, description="Offset for paging. Use next_start_index from a previous result.")
]
FilingCategory = Literal[
    "accounts",
    "address",
    "annual-return",
    "capital",
    "change-of-name",
    "confirmation-statement",
    "incorporation",
    "insolvency",
    "liquidation",
    "miscellaneous",
    "mortgage",
    "officers",
    "persons-with-significant-control",
    "resolution",
]


def _read_only(title: str) -> ToolAnnotations:
    return ToolAnnotations(
        title=title, read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
    )


@contextmanager
def _as_tool_errors() -> Iterator[None]:
    """Anticipated failures reach the model as their own message; anything else is a crash."""
    try:
        yield
    except CompaniesHouseError as exc:
        raise ToolError(str(exc)) from exc


def build_server(client: CompaniesHouseClient) -> MCPServer:
    @asynccontextmanager
    async def lifespan(_: MCPServer) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await client.aclose()

    mcp = MCPServer(
        name="companies-house",
        title="Companies House",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://find-and-update.company-information.service.gov.uk/",
        lifespan=lifespan,
    )

    @mcp.tool(annotations=_read_only("Search companies"))
    async def search_companies(
        query: Annotated[
            str, Field(min_length=1, max_length=160, description="Company name or part of it. Not a person's name.")
        ],
        limit: Annotated[int, Field(ge=1, le=50, description="Results per page.")] = 10,
        start_index: StartIndex = 0,
    ) -> CompanySearchResult:
        """Find companies on the UK register by name, returning their company numbers.

        Covers live and dissolved companies alike, ranked by relevance; check `status`
        before assuming a hit is trading. Use the returned company_number with every
        other tool. It searches company names only, so it cannot find a company from a
        director's name.
        """
        with _as_tool_errors():
            q = " ".join(query.split())
            if not q:
                raise ToolError("query is empty. Pass a company name, or part of one.")
            raw = await client.search_companies(q, limit, start_index)
            return shaping.search_result(q, raw, start_index)

    @mcp.tool(annotations=_read_only("Company profile"))
    async def get_company_profile(company_number: CompanyNumber) -> CompanyProfile:
        """Get a company's register entry: name, status, type, incorporation date, registered
        office, business activities (SIC codes), previous names, and filing deadlines.

        Read `warnings` first: it lists overdue accounts or confirmation statements,
        insolvency history, proposals to strike off, and a disputed or undeliverable
        registered office. `has_charges` says whether list_charges will find anything.
        One upstream request.
        """
        with _as_tool_errors():
            number = normalise_company_number(company_number)
            return shaping.company_profile(await client.company_profile(number))

    @mcp.tool(annotations=_read_only("List officers"))
    async def list_officers(
        company_number: CompanyNumber,
        include_resigned: Annotated[
            bool, Field(description="Include former officers. Off by default: most questions are about who is in post.")
        ] = False,
        limit: Annotated[
            int, Field(ge=1, le=100, description="Officers per page, before resigned ones are removed.")
        ] = 35,
        start_index: StartIndex = 0,
    ) -> OfficerList:
        """List a company's directors, secretaries and LLP members, with appointment dates,
        occupation, nationality and month and year of birth.

        `active_count` and `resigned_count` cover the whole company even when one page does
        not. Addresses are deliberately left out.
        """
        with _as_tool_errors():
            number = normalise_company_number(company_number)
            raw = await client.officers(number, limit, start_index)
            return shaping.officer_list(number, raw, start_index, include_resigned)

    @mcp.tool(annotations=_read_only("List filings"))
    async def list_filings(
        company_number: CompanyNumber,
        category: Annotated[
            FilingCategory | None,
            Field(description="Only filings of this kind, e.g. 'accounts' or 'officers'. Omit for everything."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100, description="Filings per page.")] = 25,
        start_index: StartIndex = 0,
    ) -> FilingList:
        """List what a company has filed at Companies House, newest first: accounts,
        confirmation statements, officer changes, charges, resolutions and so on, each
        with its form code and a readable description.

        Use `category` rather than paging through everything. Document contents are not
        returned, only whether a copy exists.
        """
        with _as_tool_errors():
            number = normalise_company_number(company_number)
            raw = await client.filing_history(number, limit, start_index, category)
            return shaping.filing_list(number, raw, start_index, category)

    @mcp.tool(annotations=_read_only("List charges"))
    async def list_charges(
        company_number: CompanyNumber,
        outstanding_only: Annotated[
            bool, Field(description="Drop fully satisfied charges. The counts still cover all charges.")
        ] = False,
        limit: Annotated[int, Field(ge=1, le=100, description="Charges per page.")] = 25,
        start_index: StartIndex = 0,
    ) -> ChargeList:
        """List charges (secured lending, such as mortgages and debentures) registered against
        a company: who holds them, when created, whether satisfied, and whether a floating
        charge covers everything the company owns.

        A company with no charges returns an empty list, not an error.
        """
        with _as_tool_errors():
            number = normalise_company_number(company_number)
            raw = await client.charges(number, limit, start_index)
            return shaping.charge_list(number, raw, start_index, outstanding_only)

    @mcp.tool(annotations=_read_only("Registered office history"))
    async def get_registered_office_history(company_number: CompanyNumber) -> RegisteredOfficeHistory:
        """Get a company's current registered office and every recorded change to it, newest
        first, with old and new addresses where the register has them.

        Frequent moves, or a move shortly before insolvency, are worth pointing out. Two
        upstream requests.
        """
        with _as_tool_errors():
            number = normalise_company_number(company_number)
            current = await client.registered_office_address(number)
            filings = await client.filing_history(number, 100, 0, "address", known_to_exist=True)
            return shaping.registered_office_history(number, current, filings)

    @mcp.tool(annotations=_read_only("People with significant control"))
    async def list_persons_with_significant_control(
        company_number: CompanyNumber,
        include_ceased: Annotated[
            bool, Field(description="Include people or entities whose control has ended.")
        ] = False,
        limit: Annotated[int, Field(ge=1, le=100, description="Entries per page.")] = 25,
        start_index: StartIndex = 0,
    ) -> PscList:
        """List who owns or controls a company (its persons with significant control): the
        people and companies holding over 25% of shares or votes, or the right to appoint
        the board, and how.

        A corporate owner comes with its registration number; if it is a UK company, pass
        that to get_company_profile to follow the chain upwards. An empty list can mean
        the company filed a statement that it has no PSC, which this tool does not read.
        """
        with _as_tool_errors():
            number = normalise_company_number(company_number)
            raw = await client.persons_with_significant_control(number, limit, start_index)
            return shaping.psc_list(number, raw, start_index, include_ceased)

    return mcp


def client_from_env() -> CompaniesHouseClient:
    return CompaniesHouseClient(
        os.environ.get("COMPANIES_HOUSE_API_KEY", "").strip() or None,
        base_url=os.environ.get("COMPANIES_HOUSE_BASE_URL", DEFAULT_BASE_URL),
        timeout_seconds=float(os.environ.get("COMPANIES_HOUSE_TIMEOUT", "10")),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="companies-house-mcp", description="Companies House MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    if not os.environ.get("COMPANIES_HOUSE_API_KEY"):
        print(
            "companies-house-mcp: COMPANIES_HOUSE_API_KEY is not set. The server will start and list "
            "its tools, but every call will return a configuration error.",
            file=sys.stderr,
        )
    server = build_server(client_from_env())
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=args.host, port=args.port)

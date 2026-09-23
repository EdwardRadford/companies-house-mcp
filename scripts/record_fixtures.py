"""Record live Companies House responses for the test suite.

    COMPANIES_HOUSE_API_KEY=... python scripts/record_fixtures.py [company_number ...]

Writes raw JSON to tests/fixtures/recorded/<company_number>/<resource>.json.
tests/test_recorded.py then runs the shaping layer over every recording, so a
field Companies House renamed or a shape the spec gets wrong shows up as a
failing test instead of a confused model. Uses the server's own client, so the
rate limiter applies; the default set is about 30 requests.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anyio

from companies_house_mcp.client import CompaniesHouseClient
from companies_house_mcp.company_number import normalise_company_number
from companies_house_mcp.errors import CompaniesHouseError

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "recorded"

# Tesco PLC: a long filing history, many officers and charges. Add a Scottish
# company, an LLP and a dissolved company on the command line for a wider spread.
DEFAULT_COMPANIES = ["00445790"]


async def record(client: CompaniesHouseClient, number: str) -> None:
    folder = OUT / number
    folder.mkdir(parents=True, exist_ok=True)
    calls = {
        "profile": client.company_profile(number),
        "officers": client.officers(number, 100, 0),
        "filing-history": client.filing_history(number, 100, 0),
        "filing-history-address": client.filing_history(number, 100, 0, "address"),
        "charges": client.charges(number, 100, 0),
        "registered-office-address": client.registered_office_address(number),
        "persons-with-significant-control": client.persons_with_significant_control(number, 100, 0),
    }
    for name, pending in calls.items():
        try:
            body = await pending
        except CompaniesHouseError as exc:
            print(f"  {number} {name}: {exc}", file=sys.stderr)
            continue
        (folder / f"{name}.json").write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  {number} {name}: {len(body.get('items', [])) or 'ok'}")


async def main(numbers: list[str]) -> int:
    key = os.environ.get("COMPANIES_HOUSE_API_KEY")
    if not key:
        print("Set COMPANIES_HOUSE_API_KEY first.", file=sys.stderr)
        return 1
    async with CompaniesHouseClient(key) as client:
        search = await client.search_companies("tesco", 20, 0)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "search-tesco.json").write_text(json.dumps(search, indent=1) + "\n", encoding="utf-8")
        for raw in numbers:
            await record(client, normalise_company_number(raw))
    return 0


if __name__ == "__main__":
    raise SystemExit(anyio.run(main, sys.argv[1:] or DEFAULT_COMPANIES))

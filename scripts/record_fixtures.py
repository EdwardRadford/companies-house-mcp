"""Record live Companies House responses for the test suite.

    COMPANIES_HOUSE_API_KEY=... python scripts/record_fixtures.py [company_number ...]

Writes raw JSON to tests/fixtures/recorded/<company_number>/<resource>.json.
tests/test_recorded.py then runs the shaping layer over every recording, so a
field Companies House renamed or a shape the spec gets wrong shows up as a
failing test instead of a confused model. Uses the server's own client, so the
rate limiter applies; each company is about 8 requests.

Recordings are committed, so natural persons are redacted before anything is
written: names, birth dates, addresses and officer ids of individual officers
and PSCs, and officer names inside filing descriptions. The server never
returns officers' addresses, and its fixtures should not publish them either.
Companies, corporate officers and every field's shape are kept as recorded.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import anyio

from companies_house_mcp.client import CompaniesHouseClient
from companies_house_mcp.company_number import normalise_company_number
from companies_house_mcp.errors import CompaniesHouseError

JSON = dict[str, Any]

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "recorded"

# Tesco PLC: a long filing history, many officers and charges. Add a Scottish
# company, an LLP and a dissolved company on the command line for a wider spread.
DEFAULT_COMPANIES = ["00445790"]


_ADDRESS = {"address_line_1": "Redacted", "locality": "Redacted", "postal_code": "XX1 1XX", "country": "England"}


def _redact_person(item: JSON, n: int) -> None:
    item["name"] = f"PERSON, Redacted {n}"
    if "name_elements" in item:
        item["name_elements"] = {"forename": "Redacted", "surname": f"Person {n}"}
    if "date_of_birth" in item:
        item["date_of_birth"] = {"month": 1, "year": 1970}
    for key in ("address", "principal_office_address"):
        if key in item:
            item[key] = dict(_ADDRESS)
    if "former_names" in item:
        item["former_names"] = [{"forenames": "Redacted", "surname": "Person"}]
    links = item.get("links")
    if isinstance(links, dict):
        if isinstance(links.get("officer"), dict):
            links["officer"] = {"appointments": "/officers/redacted/appointments"}
        if isinstance(links.get("self"), str):
            links["self"] = links["self"].rsplit("/", 1)[0] + "/redacted"


def _is_natural_person(resource: str, item: JSON) -> bool:
    if resource == "officers":
        return not str(item.get("officer_role", "")).startswith("corporate")
    if resource == "persons-with-significant-control":
        return str(item.get("kind", "")).startswith(("individual", "super-secure"))
    return False


def redact(resource: str, body: JSON) -> JSON:
    items = body.get("items") if isinstance(body.get("items"), list) else []
    for n, item in enumerate(i for i in items if isinstance(i, dict)):
        if _is_natural_person(resource, item):
            _redact_person(item, n + 1)
        elif resource.startswith("filing-history"):
            values = item.get("description_values")
            if isinstance(values, dict):
                _redact_filing_values(str(item.get("type", "")), values)
    return body


_CORPORATE = re.compile(r"\b(limited|ltd|llp|plc|lp|company|services|secretaries|nominees)\b", re.IGNORECASE)
_LEGACY_OFFICER = re.compile(
    r"^((?:new )?(?:director|secretary|member)(?:'s)? (?:appointed|resigned|change of particulars|particulars changed)"
    r"|appointment terminated (?:director|secretary|member))(\W+)(.+)$",
    re.IGNORECASE,
)


def _redact_filing_values(form: str, values: JSON) -> None:
    for key in ("officer_name", "psc_name"):
        if isinstance(values.get(key), str) and not _CORPORATE.search(values[key]):
            values[key] = "Redacted Person"
    text = values.get("description")
    if form.upper().startswith(("288", "LLP288")) and isinstance(text, str):
        match = _LEGACY_OFFICER.match(text.strip())
        if match and not _CORPORATE.search(match.group(3)):
            values["description"] = f"{match.group(1)} Redacted Person"


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
        body = redact(name, body)
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

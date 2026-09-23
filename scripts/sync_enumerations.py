"""Refresh the vendored Companies House enumerations.

Companies House publishes the lookup tables its own website uses (filing
descriptions, company statuses, PSC natures of control, SIC codes) as YAML in
github.com/companieshouse/api-enumerations. The API returns keys into those
tables, not text, so without them a model sees
"change-registered-office-address-company-with-date-old-address-new-address"
instead of a sentence.

This script pulls the sections the server uses and writes them to a single JSON
file inside the package, so the runtime needs neither the network nor PyYAML.

    python scripts/sync_enumerations.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import yaml

REPO = "https://raw.githubusercontent.com/companieshouse/api-enumerations/master"
OUT = Path(__file__).resolve().parents[1] / "src" / "companies_house_mcp" / "data" / "enumerations.json"

# (source file, section in that file, key in our JSON)
SECTIONS = [
    ("constants.yml", "company_status", "company_status"),
    ("constants.yml", "company_status_detail", "company_status_detail"),
    ("constants.yml", "company_type", "company_type"),
    ("constants.yml", "jurisdiction", "jurisdiction"),
    ("constants.yml", "officer_role", "officer_role"),
    ("constants.yml", "sic_descriptions", "sic_descriptions"),
    ("filing_history_descriptions.yml", "description", "filing_description"),
    ("psc_descriptions.yml", "short_description", "psc_nature_of_control"),
]


def fetch(name: str) -> dict:
    with urllib.request.urlopen(f"{REPO}/{name}", timeout=30) as resp:
        return yaml.safe_load(resp.read())


def main() -> int:
    sources: dict[str, dict] = {}
    out: dict[str, object] = {
        "_source": REPO,
        "_fetched": datetime.now(UTC).strftime("%Y-%m-%d"),
    }
    for filename, section, key in SECTIONS:
        if filename not in sources:
            sources[filename] = fetch(filename)
        table = sources[filename].get(section)
        if not isinstance(table, dict) or not table:
            print(f"missing section {section} in {filename}", file=sys.stderr)
            return 1
        out[key] = {str(k): str(v) for k, v in table.items()}
        print(f"{key}: {len(table)} entries")
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

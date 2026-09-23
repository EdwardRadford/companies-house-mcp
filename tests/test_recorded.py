"""Shape every live recording (see scripts/record_fixtures.py).

This is the check that the shaping layer holds up on the real API, not just on
fixtures written from its specification.
"""

import json
from pathlib import Path

import pytest

from companies_house_mcp import shaping

RECORDED = Path(__file__).parent / "fixtures" / "recorded"
FILES = sorted(RECORDED.glob("*/*.json")) if RECORDED.exists() else []


def _shape(resource: str, number: str, raw: dict) -> object:  # type: ignore[type-arg]
    match resource:
        case "profile":
            return shaping.company_profile(raw)
        case "officers":
            return shaping.officer_list(number, raw, 0, include_resigned=True)
        case "filing-history" | "filing-history-address":
            return shaping.filing_list(number, raw, 0, None)
        case "charges":
            return shaping.charge_list(number, raw, 0, outstanding_only=False)
        case "registered-office-address":
            return shaping.registered_office_history(number, raw, {"items": []})
        case "persons-with-significant-control":
            return shaping.psc_list(number, raw, 0, include_ceased=True)
    raise AssertionError(f"no shaper for {resource}")


@pytest.mark.skipif(not FILES, reason="no live recordings yet; run scripts/record_fixtures.py with an API key")
@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_recording_shapes_cleanly(path: Path) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    shaped = _shape(path.stem, path.parent.name, raw)
    dumped = shaped.model_dump(mode="json")  # type: ignore[attr-defined]
    assert dumped["company_number"] == path.parent.name
    if path.stem == "filing-history":
        descriptions = [f["description"] for f in dumped["filings"]]
        assert all(d and "{" not in d for d in descriptions), "a filing template was left unrendered"

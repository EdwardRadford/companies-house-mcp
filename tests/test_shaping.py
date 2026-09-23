"""Shaping is total: odd records degrade to None, never to an exception."""

from companies_house_mcp import enumerations as enums
from companies_house_mcp import shaping


def test_unknown_enumeration_key_is_humanised_not_dropped() -> None:
    assert enums.label("company_status", "some-new-status") == "Some new status"
    assert enums.label("company_status", None) is None


def test_filing_with_unknown_key_and_no_text_still_reads() -> None:
    assert enums.filing_description("brand-new-form-type", {}) == "Brand new form type"


def test_filing_template_with_missing_value_does_not_leave_braces() -> None:
    text = enums.filing_description("confirmation-statement-with-no-updates", {})
    assert "{" not in text
    assert text.startswith("Confirmation statement made on")


def test_address_formatting() -> None:
    assert shaping.one_line_address({"po_box": "12", "locality": "Leeds", "postal_code": "LS1 1AA"}) == (
        "PO Box 12, Leeds, LS1 1AA"
    )
    assert shaping.one_line_address({}) is None
    assert shaping.one_line_address("not an object") is None


def test_year_month() -> None:
    assert shaping.year_month({"year": 1981, "month": 7}) == "1981-07"
    assert shaping.year_month({"year": 1981}) == "1981"
    assert shaping.year_month({"month": 7}) is None
    assert shaping.year_month(None) is None


def test_next_start() -> None:
    assert shaping.next_start(0, 25, 100) == 25
    assert shaping.next_start(75, 25, 100) is None
    assert shaping.next_start(0, 0, 100) is None, "an empty page must not loop the caller"


def test_sparse_profile_does_not_crash() -> None:
    profile = shaping.company_profile(
        {"company_number": "01234567", "date_of_creation": "not-a-date", "sic_codes": None}
    )
    assert profile.company_number == "01234567"
    assert profile.incorporated_on is None
    assert profile.accounts is None
    assert profile.warnings == []


def test_garbled_list_items_are_skipped() -> None:
    raw = {"items": ["junk", None, {"name": "SMITH, Jo", "officer_role": "director"}], "total_results": "3"}
    out = shaping.officer_list("01234567", raw, 0, include_resigned=True)
    assert [o.name for o in out.officers] == ["SMITH, Jo"]

"""The server as a model sees it: tools called over MCP, results read back as JSON."""

import pytest
from mcp import Client

from .conftest import FakeCompaniesHouse, Reply, call, call_error

pytestmark = pytest.mark.anyio


# -- search ------------------------------------------------------------------


async def test_search_returns_numbers_and_readable_status(session: Client) -> None:
    out = await call(session, "search_companies", query="  Halcyon   Forge ", limit=2)
    assert out["query"] == "Halcyon Forge"
    assert out["total_results"] == 3
    first, second = out["results"]
    assert first == {
        "company_number": "09446231",
        "name": "HALCYON FORGE LIMITED",
        "status": "Active",
        "type": "Private limited company",
        "incorporated_on": "2015-02-17",
        "dissolved_on": None,
        "address": "Unit 4 Kiln Farm, Tanners Drive, Milton Keynes, MK11 3JB",
    }
    assert second["status"] == "Dissolved"
    assert second["dissolved_on"] == "2019-06-25"
    assert out["next_start_index"] == 2


async def test_search_with_no_hits_is_a_result_not_an_error(session: Client) -> None:
    out = await call(session, "search_companies", query="zzqx nothing")
    assert out == {"query": "zzqx nothing", "total_results": 0, "results": [], "next_start_index": None}


async def test_whitespace_query_is_refused(session: Client, ch: FakeCompaniesHouse) -> None:
    message = await call_error(session, "search_companies", query="   ")
    assert "company name" in message
    assert ch.requests == []


# -- profile -----------------------------------------------------------------


async def test_profile_of_healthy_company(session: Client) -> None:
    out = await call(session, "get_company_profile", company_number="9446231")
    assert out["company_number"] == "09446231"
    assert out["jurisdiction"] == "England/Wales"
    assert (
        out["registered_office"] == "Unit 4 Kiln Farm, Tanners Drive, Milton Keynes, Buckinghamshire, MK11 3JB, England"
    )
    assert out["sic_codes"][1] == {"code": "62020", "description": "Information technology consultancy activities"}
    assert out["previous_names"] == [
        {"name": "HALCYON FABRICATION LIMITED", "used_from": "2015-02-17", "used_until": "2018-09-03"}
    ]
    assert out["accounts"]["last_type"] == "micro-entity"
    assert out["accounts"]["next_due"] == "2027-11-30"
    assert out["has_charges"] is True
    assert out["warnings"] == []


async def test_profile_of_troubled_company_surfaces_every_red_flag(session: Client) -> None:
    out = await call(session, "get_company_profile", company_number="sc 654321")
    assert out["company_number"] == "SC654321"
    assert out["registered_office"].startswith("c/o Firth & Mowat Recovery LLP, 3 Castle Wynd")
    assert out["accounts"]["last_type"] is None
    warnings = " | ".join(out["warnings"])
    for expected in (
        "Company status is Liquidation",
        "strike off",
        "Accounts are overdue, due by 2025-12-02",
        "Confirmation statement is overdue",
        "insolvency history",
        "in dispute",
        "undeliverable",
    ):
        assert expected.lower() in warnings.lower(), expected


async def test_unknown_company_tells_the_model_how_to_recover(session: Client) -> None:
    message = await call_error(session, "get_company_profile", company_number="01234567")
    assert "No company with number 01234567" in message
    assert "search_companies" in message


async def test_malformed_number_is_refused_before_any_request(session: Client, ch: FakeCompaniesHouse) -> None:
    message = await call_error(session, "get_company_profile", company_number="TESCO")
    assert "not a valid UK company number" in message
    assert ch.requests == []


# -- officers ----------------------------------------------------------------


async def test_officers_default_to_current(session: Client) -> None:
    out = await call(session, "list_officers", company_number="09446231")
    assert [o["name"] for o in out["officers"]] == [
        "OKONKWO-HALE, Adaeze Rosalind",
        "BRANDT, Tomasz",
        "LEDGERLINE SECRETARIES LIMITED",
    ]
    assert (out["active_count"], out["resigned_count"], out["resigned_omitted"]) == (3, 2, 2)
    first = out["officers"][0]
    assert first["role"] == "Director"
    assert first["born"] == "1981-07"
    assert "address" not in first, "officer addresses are deliberately not exposed"
    assert out["officers"][2]["role"] == "Secretary"


async def test_officers_can_include_resigned(session: Client) -> None:
    out = await call(session, "list_officers", company_number="09446231", include_resigned=True)
    assert len(out["officers"]) == 5
    assert out["resigned_omitted"] == 0
    assert out["officers"][3]["resigned_on"] == "2019-11-04"


# -- filings -----------------------------------------------------------------


async def test_filings_are_described_in_words(session: Client) -> None:
    out = await call(session, "list_filings", company_number="09446231")
    descriptions = [f["description"] for f in out["filings"]]
    assert descriptions == [
        "Confirmation statement made on 2026-02-17 with no updates",
        "Micro company accounts made up to 2025-02-28",
        "Registration of charge 094462310002, created on 2024-06-05",
        "Registered office address changed from 12 Silbury Boulevard Milton Keynes MK9 2AF to "
        "Unit 4 Kiln Farm Tanners Drive Milton Keynes MK11 3JB on 2021-05-10",
        "Appointment of Mr Tomasz Brandt as a director on 2019-11-04",
        "Section 519 statement from outgoing auditor",
    ]
    assert [f["form"] for f in out["filings"]][:2] == ["CS01", "AA"]
    assert out["filings"][0]["document_available"] is True
    assert out["filings"][3]["document_available"] is False
    assert (out["total"], out["next_start_index"]) == (41, 6)


async def test_filing_category_is_passed_upstream(session: Client, ch: FakeCompaniesHouse) -> None:
    out = await call(session, "list_filings", company_number="09446231", category="address")
    assert out["category"] == "address"
    assert ch.requests[-1].url.params["category"] == "address"


async def test_unknown_filing_category_is_rejected_by_schema(session: Client, ch: FakeCompaniesHouse) -> None:
    await call_error(session, "list_filings", company_number="09446231", category="gossip")
    assert ch.requests == []


# -- charges -----------------------------------------------------------------


async def test_charges(session: Client) -> None:
    out = await call(session, "list_charges", company_number="09446231")
    assert (out["total"], out["outstanding"], out["satisfied"]) == (2, 1, 1)
    live, old = out["charges"]
    assert live["reference"] == "094462310002"
    assert live["lenders"] == ["Kestrel Asset Finance PLC"]
    assert live["floating_charge_covers_all"] is True
    assert live["negative_pledge"] is True
    assert live["description"] == "A registered charge"
    assert old["reference"] == "Charge 1"
    assert old["description"] == "Debenture"
    assert old["secures"].startswith("All monies due")
    assert old["satisfied_on"] == "2023-10-02"


async def test_outstanding_only_keeps_whole_company_counts(session: Client) -> None:
    out = await call(session, "list_charges", company_number="09446231", outstanding_only=True)
    assert [c["status"] for c in out["charges"]] == ["outstanding"]
    assert out["total"] == 2


async def test_company_without_charges_gets_empty_list(session: Client) -> None:
    out = await call(session, "list_charges", company_number="SC654321")
    assert (out["total"], out["charges"]) == (0, [])


async def test_lists_for_a_company_that_does_not_exist_say_so(session: Client) -> None:
    for tool in ("list_charges", "list_officers", "list_filings", "list_persons_with_significant_control"):
        message = await call_error(session, tool, company_number="01234567")
        assert "No company with number 01234567" in message, tool


# -- registered office -------------------------------------------------------


async def test_registered_office_history(session: Client) -> None:
    out = await call(session, "get_registered_office_history", company_number="09446231")
    assert out["current_address"].startswith("Unit 4 Kiln Farm")
    changes = out["changes"]
    assert [c["form"] for c in changes] == ["RP05", "AD01", "AD01", "287"], "inspection-location filings are not moves"
    default, recent, older, paper = changes
    assert default["to_companies_house_default"] is True
    assert default["new_address"].startswith("PO Box 4385")
    assert recent["old_address"] == "12 Silbury Boulevard, Milton Keynes, MK9 2AF", "stray upstream commas tidied"
    assert recent["changed_on"] == "2021-05-10"
    assert older["old_address"] == "Flat 2 Oldbrook Crescent Milton Keynes MK6 2NH"
    assert paper["old_address"] is None
    assert "4 old yard" in paper["description"]
    assert out["complete"] is True


# -- PSCs --------------------------------------------------------------------


async def test_pscs_default_to_current_and_read_as_words(session: Client) -> None:
    out = await call(session, "list_persons_with_significant_control", company_number="09446231")
    assert (out["active_count"], out["ceased_count"], out["ceased_omitted"]) == (2, 1, 1)
    person, company = out["people"]
    assert person["kind"] == "individual"
    assert person["born"] == "1981-07"
    assert person["control"][0].startswith("Ownership of shares")
    assert "50%" in person["control"][0]
    assert company["kind"] == "corporate entity"
    assert company["registration_number"] == "11223344"
    assert company["born"] is None


async def test_pscs_can_include_ceased(session: Client) -> None:
    out = await call(session, "list_persons_with_significant_control", company_number="09446231", include_ceased=True)
    assert out["people"][2]["ceased_on"] == "2019-11-04"


# -- failure modes end to end ------------------------------------------------


async def test_rate_limit_reaches_the_model_as_advice(session: Client, ch: FakeCompaniesHouse) -> None:
    ch.on("/company/09446231", Reply(429, {}, {"X-Ratelimit-Reset": "0"}))
    message = await call_error(session, "get_company_profile", company_number="09446231")
    assert "rate limit" in message
    assert "Do not retry straight away" in message


async def test_outage_reaches_the_model_as_theirs_not_ours(session: Client, ch: FakeCompaniesHouse) -> None:
    ch.on("/company/09446231/officers", Reply(503))
    message = await call_error(session, "list_officers", company_number="09446231")
    assert "on their side" in message


async def test_out_of_range_limit_is_rejected_without_a_request(session: Client, ch: FakeCompaniesHouse) -> None:
    await call_error(session, "list_officers", company_number="09446231", limit=500)
    await call_error(session, "search_companies", query="x", limit=0)
    assert ch.requests == []

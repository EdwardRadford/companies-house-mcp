import pytest

from companies_house_mcp.company_number import normalise_company_number
from companies_house_mcp.errors import InvalidCompanyNumber


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00445790", "00445790"),
        ("445790", "00445790"),
        (" 445790 ", "00445790"),
        ("04 12 34 56", "04123456"),
        ("04-123-456", "04123456"),
        ("sc123456", "SC123456"),
        ("SC 123456", "SC123456"),
        ("SC1234", "SC001234"),
        ("OC301234", "OC301234"),
        ("NI012345", "NI012345"),
        ("R0000123", "R0000123"),
        ("Company No. 04123456", "04123456"),
        ("no: 445790", "00445790"),
    ],
)
def test_normalises_what_models_actually_send(raw: str, expected: str) -> None:
    assert normalise_company_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "abc", "123456789", "S1234567", "SC1234567", "00000000", "0", "TESCO PLC", "12AB3456", "SC-ABCDEF"],
)
def test_rejects_what_cannot_be_a_company_number(raw: str) -> None:
    with pytest.raises(InvalidCompanyNumber) as err:
        normalise_company_number(raw)
    assert "search_companies" in str(err.value), "the error must point the model at the recovery path"

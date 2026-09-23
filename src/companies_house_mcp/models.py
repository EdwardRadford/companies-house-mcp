"""What the tools return.

These are deliberately not the Companies House response schemas. The raw API
is shaped for a website: nested address objects, enumeration keys instead of
words, links, etags, and twenty fields the page never shows. A model pays for
every one of those tokens and then has to interpret them. So each model here
keeps only what answers a real question about a company, in words, with dates
as dates, and says in its field descriptions what a value means when that is
not obvious (e.g. that officers' birth dates are month and year only).

Field descriptions become the tool's output schema, so they are written for
the model reading the result.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


NextStart = Field(
    default=None,
    description="Pass this as start_index to get the next page. Null when there are no more results.",
)
YearMonth = Field(
    default=None,
    description="Year and month of birth as YYYY-MM. Companies House never publishes the day.",
)


# -- search ------------------------------------------------------------------


class CompanySearchHit(_Model):
    company_number: str
    name: str
    status: str | None = Field(description="e.g. Active, Dissolved, Liquidation.")
    type: str | None = Field(description="e.g. Private limited company.")
    incorporated_on: date | None = None
    dissolved_on: date | None = None
    address: str | None = Field(default=None, description="Registered office, one line.")


class CompanySearchResult(_Model):
    query: str
    total_results: int = Field(description="Matches on the whole register, not just this page.")
    results: list[CompanySearchHit]
    next_start_index: int | None = NextStart


# -- profile -----------------------------------------------------------------


class SicCode(_Model):
    code: str
    description: str | None


class PreviousName(_Model):
    name: str
    used_from: date | None = None
    used_until: date | None = None


class AccountsStatus(_Model):
    last_made_up_to: date | None = None
    last_type: str | None = Field(default=None, description="e.g. micro-entity, small, full, dormant.")
    next_made_up_to: date | None = None
    next_due: date | None = None
    overdue: bool = False


class ConfirmationStatementStatus(_Model):
    last_made_up_to: date | None = None
    next_due: date | None = None
    overdue: bool = False


class CompanyProfile(_Model):
    company_number: str
    name: str
    status: str | None
    status_detail: str | None = None
    type: str | None
    jurisdiction: str | None = None
    incorporated_on: date | None = None
    dissolved_on: date | None = None
    registered_office: str | None = Field(default=None, description="One line, as on the register.")
    sic_codes: list[SicCode] = Field(default_factory=list, description="Declared business activities.")
    previous_names: list[PreviousName] = Field(default_factory=list)
    accounts: AccountsStatus | None = None
    confirmation_statement: ConfirmationStatementStatus | None = None
    has_charges: bool = Field(default=False, description="True if any charge (secured lending) was ever registered.")
    has_insolvency_history: bool = False
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Plain-English red flags derived from the record: overdue filings, insolvency, "
            "a disputed or undeliverable registered office. Empty means none were found, "
            "not that the company has been vetted."
        ),
    )


# -- officers ----------------------------------------------------------------


class Officer(_Model):
    name: str
    role: str | None = Field(description="e.g. Director, Secretary, LLP Designated Member.")
    appointed_on: date | None = None
    resigned_on: date | None = Field(default=None, description="Null while still in post.")
    occupation: str | None = None
    nationality: str | None = None
    country_of_residence: str | None = None
    born: str | None = YearMonth


class OfficerList(_Model):
    company_number: str
    active_count: int
    resigned_count: int
    officers: list[Officer]
    resigned_omitted: int = Field(
        default=0, description="Resigned officers on this page left out because include_resigned was false."
    )
    next_start_index: int | None = NextStart


# -- filings -----------------------------------------------------------------


class Filing(_Model):
    filed_on: date | None
    form: str | None = Field(description="Companies House form code, e.g. CS01, AA, AP01, AD01.")
    category: str | None
    description: str
    document_available: bool = Field(
        default=False, description="Whether a scanned or electronic copy exists on the register."
    )


class FilingList(_Model):
    company_number: str
    category: str | None
    total: int
    filings: list[Filing] = Field(description="Newest first.")
    next_start_index: int | None = NextStart


# -- charges -----------------------------------------------------------------


class Charge(_Model):
    reference: str = Field(description="Charge code (post-2013) or charge number.")
    status: str = Field(description="outstanding, part-satisfied or fully-satisfied.")
    description: str | None = Field(default=None, description="e.g. 'A registered charge', 'Debenture'.")
    created_on: date | None = None
    delivered_on: date | None = None
    satisfied_on: date | None = None
    lenders: list[str] = Field(default_factory=list, description="Persons entitled to the charge.")
    more_than_four_lenders: bool = False
    fixed_charge: bool | None = None
    floating_charge: bool | None = None
    floating_charge_covers_all: bool | None = Field(
        default=None, description="True means the floating charge covers the whole of the company's property."
    )
    negative_pledge: bool | None = Field(
        default=None, description="True means the company promised not to grant other security ranking ahead."
    )
    secures: str | None = Field(default=None, description="What the charge secures, where stated.")
    particulars: str | None = Field(default=None, description="Short description of the charged property.")


class ChargeList(_Model):
    company_number: str
    total: int
    outstanding: int = Field(description="Outstanding or only part-satisfied.")
    satisfied: int
    charges: list[Charge]
    next_start_index: int | None = NextStart


# -- registered office -------------------------------------------------------


class AddressChange(_Model):
    changed_on: date | None = Field(description="Date the change took effect.")
    filed_on: date | None = None
    old_address: str | None = None
    new_address: str | None = None
    form: str | None = None


class RegisteredOfficeHistory(_Model):
    company_number: str
    current_address: str | None
    changes: list[AddressChange] = Field(description="Newest first.")
    complete: bool = Field(
        description=(
            "False if there were more address filings than one page holds. Paper-era changes "
            "can also lack the old and new address text."
        )
    )


# -- people with significant control ----------------------------------------


PscKind = Literal["individual", "corporate entity", "legal person", "super-secure", "other"]


class PersonWithSignificantControl(_Model):
    name: str | None = Field(description="Null for super-secure (protected) entries.")
    kind: PscKind
    beneficial_owner: bool = Field(
        default=False, description="True for overseas-entity beneficial owner entries rather than UK PSCs."
    )
    notified_on: date | None = None
    ceased_on: date | None = Field(default=None, description="Null while control continues.")
    control: list[str] = Field(description="Natures of control, e.g. 'Ownership of shares - More than 75%'.")
    nationality: str | None = None
    country_of_residence: str | None = None
    born: str | None = YearMonth
    registration_number: str | None = Field(
        default=None,
        description=(
            "For a corporate PSC, its registration number. If it is registered in England, Wales, "
            "Scotland or Northern Ireland, pass it to get_company_profile to follow the ownership chain."
        ),
    )
    place_registered: str | None = None
    legal_form: str | None = None


class PscList(_Model):
    company_number: str
    active_count: int
    ceased_count: int
    people: list[PersonWithSignificantControl]
    ceased_omitted: int = Field(
        default=0, description="Ceased entries on this page left out because include_ceased was false."
    )
    next_start_index: int | None = NextStart

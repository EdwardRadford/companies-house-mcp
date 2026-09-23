"""Raw Companies House JSON in, model-shaped results out.

Everything here is pure and total: missing or oddly typed fields become None
or are skipped, never an exception, because the register holds a century of
records and not all of them are tidy.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import enumerations as enums
from .models import (
    AccountsStatus,
    AddressChange,
    Charge,
    ChargeList,
    CompanyProfile,
    CompanySearchHit,
    CompanySearchResult,
    ConfirmationStatementStatus,
    Filing,
    FilingList,
    Officer,
    OfficerList,
    PersonWithSignificantControl,
    PreviousName,
    PscKind,
    PscList,
    RegisteredOfficeHistory,
    SicCode,
)

JSON = dict[str, Any]


def _d(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _obj(value: Any) -> JSON:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[JSON]:
    return [i for i in value if isinstance(i, dict)] if isinstance(value, list) else []


def _first(value: Any) -> JSON:
    """Some fields are an object in live responses and an array in the spec. Accept both."""
    if isinstance(value, dict):
        return value
    items = _items(value)
    return items[0] if items else {}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def next_start(start_index: int, page_count: int, total: int) -> int | None:
    following = start_index + page_count
    return following if page_count and following < total else None


def one_line_address(raw: Any) -> str | None:
    a = _obj(raw)
    parts = []
    if a.get("care_of"):
        parts.append(f"c/o {a['care_of']}")
    if a.get("po_box"):
        parts.append(f"PO Box {a['po_box']}")
    first_line = " ".join(str(a[k]).strip() for k in ("premises", "address_line_1") if a.get(k))
    parts.extend([first_line] if first_line else [])
    for key in ("address_line_2", "locality", "region", "postal_code", "country"):
        if a.get(key):
            parts.append(str(a[key]).strip())
    return ", ".join(p for p in parts if p) or None


def year_month(raw: Any) -> str | None:
    dob = _obj(raw)
    year, month = _int(dob.get("year"), 0), _int(dob.get("month"), 0)
    if not year:
        return None
    return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else f"{year:04d}"


# -- search ------------------------------------------------------------------


def search_result(query: str, raw: JSON, start_index: int) -> CompanySearchResult:
    items = _items(raw.get("items"))
    hits = [
        CompanySearchHit(
            company_number=str(i.get("company_number", "")),
            name=str(i.get("title") or i.get("company_name") or ""),
            status=enums.label("company_status", i.get("company_status")),
            type=enums.label("company_type", i.get("company_type")),
            incorporated_on=_d(i.get("date_of_creation")),
            dissolved_on=_d(i.get("date_of_cessation")),
            address=i.get("address_snippet") or one_line_address(i.get("address")),
        )
        for i in items
        if i.get("company_number")
    ]
    total = _int(raw.get("total_results"), len(hits))
    return CompanySearchResult(
        query=query, total_results=total, results=hits, next_start_index=next_start(start_index, len(items), total)
    )


# -- profile -----------------------------------------------------------------


def company_profile(raw: JSON) -> CompanyProfile:
    status_key = raw.get("company_status")
    status = enums.label("company_status", status_key)
    detail_key = raw.get("company_status_detail")
    detail = enums.label("company_status_detail", detail_key) if detail_key else None

    acc = _obj(raw.get("accounts"))
    last = _obj(acc.get("last_accounts"))
    nxt = _obj(acc.get("next_accounts"))
    accounts = (
        AccountsStatus(
            last_made_up_to=_d(last.get("made_up_to") or last.get("period_end_on")),
            last_type=last.get("type") if last.get("type") not in (None, "null") else None,
            next_made_up_to=_d(acc.get("next_made_up_to") or nxt.get("period_end_on")),
            next_due=_d(acc.get("next_due") or nxt.get("due_on")),
            overdue=bool(acc.get("overdue") or nxt.get("overdue")),
        )
        if acc
        else None
    )
    cs = _obj(raw.get("confirmation_statement"))
    confirmation = (
        ConfirmationStatementStatus(
            last_made_up_to=_d(cs.get("last_made_up_to")),
            next_due=_d(cs.get("next_due")),
            overdue=bool(cs.get("overdue")),
        )
        if cs
        else None
    )

    warnings: list[str] = []
    if status_key and status_key != "active":
        ceased = _d(raw.get("date_of_cessation"))
        warnings.append(f"Company status is {status}" + (f" (since {ceased.isoformat()})." if ceased else "."))
    if detail:
        warnings.append(f"Status detail: {detail}.")
    if accounts and accounts.overdue:
        due = f", due by {accounts.next_due.isoformat()}" if accounts.next_due else ""
        warnings.append(f"Accounts are overdue{due}.")
    if confirmation and confirmation.overdue:
        due = f", due by {confirmation.next_due.isoformat()}" if confirmation.next_due else ""
        warnings.append(f"Confirmation statement is overdue{due}.")
    if raw.get("has_insolvency_history"):
        warnings.append("The company has an insolvency history on the register.")
    if raw.get("has_been_liquidated"):
        warnings.append("The company has been liquidated.")
    if raw.get("registered_office_is_in_dispute"):
        warnings.append("The registered office address is in dispute.")
    if raw.get("undeliverable_registered_office_address"):
        warnings.append("Mail to the registered office has been returned as undeliverable.")

    return CompanyProfile(
        company_number=str(raw.get("company_number", "")),
        name=str(raw.get("company_name", "")),
        status=status,
        status_detail=detail,
        type=enums.label("company_type", raw.get("type")),
        jurisdiction=enums.label("jurisdiction", raw.get("jurisdiction")),
        incorporated_on=_d(raw.get("date_of_creation")),
        dissolved_on=_d(raw.get("date_of_cessation")),
        registered_office=one_line_address(raw.get("registered_office_address")),
        sic_codes=[SicCode(code=str(c), description=enums.sic_description(str(c))) for c in raw.get("sic_codes") or []],
        previous_names=[
            PreviousName(
                name=str(p.get("name", "")), used_from=_d(p.get("effective_from")), used_until=_d(p.get("ceased_on"))
            )
            for p in _items(raw.get("previous_company_names"))
        ],
        accounts=accounts,
        confirmation_statement=confirmation,
        has_charges=bool(raw.get("has_charges")),
        has_insolvency_history=bool(raw.get("has_insolvency_history")),
        warnings=warnings,
    )


# -- officers ----------------------------------------------------------------


def officer_list(company_number: str, raw: JSON, start_index: int, include_resigned: bool) -> OfficerList:
    items = _items(raw.get("items"))
    officers = []
    omitted = 0
    for i in items:
        if i.get("resigned_on") and not include_resigned:
            omitted += 1
            continue
        officers.append(
            Officer(
                name=str(i.get("name", "")),
                role=enums.label("officer_role", i.get("officer_role")),
                appointed_on=_d(i.get("appointed_on")),
                resigned_on=_d(i.get("resigned_on")),
                occupation=i.get("occupation"),
                nationality=i.get("nationality"),
                country_of_residence=i.get("country_of_residence"),
                born=year_month(i.get("date_of_birth")),
            )
        )
    total = _int(raw.get("total_results"), len(items))
    return OfficerList(
        company_number=company_number,
        active_count=_int(raw.get("active_count")),
        resigned_count=_int(raw.get("resigned_count")),
        officers=officers,
        resigned_omitted=omitted,
        next_start_index=next_start(start_index, len(items), total),
    )


# -- filings -----------------------------------------------------------------


def _filing(i: JSON) -> Filing:
    return Filing(
        filed_on=_d(i.get("date")),
        form=i.get("type"),
        category=i.get("category"),
        description=enums.filing_description(i.get("description"), _obj(i.get("description_values"))),
        document_available=bool(_obj(i.get("links")).get("document_metadata")),
    )


def filing_list(company_number: str, raw: JSON, start_index: int, category: str | None) -> FilingList:
    items = _items(raw.get("items"))
    total = _int(raw.get("total_count"), len(items))
    return FilingList(
        company_number=company_number,
        category=category,
        total=total,
        filings=[_filing(i) for i in items],
        next_start_index=next_start(start_index, len(items), total),
    )


# -- charges -----------------------------------------------------------------


def _charge(i: JSON) -> Charge:
    particulars = _first(i.get("particulars"))
    secured = _first(i.get("secured_details"))
    classification = _first(i.get("classification"))
    reference = i.get("charge_code") or (f"Charge {i['charge_number']}" if i.get("charge_number") else i.get("id"))
    return Charge(
        reference=str(reference or "unknown"),
        status=str(i.get("status") or "unknown"),
        description=classification.get("description"),
        created_on=_d(i.get("created_on")),
        delivered_on=_d(i.get("delivered_on")),
        satisfied_on=_d(i.get("satisfied_on")),
        lenders=[str(p["name"]) for p in _items(i.get("persons_entitled")) if p.get("name")],
        more_than_four_lenders=bool(i.get("more_than_four_persons_entitled")),
        fixed_charge=particulars.get("contains_fixed_charge"),
        floating_charge=particulars.get("contains_floating_charge"),
        floating_charge_covers_all=particulars.get("floating_charge_covers_all"),
        negative_pledge=particulars.get("contains_negative_pledge"),
        secures=secured.get("description"),
        particulars=particulars.get("description"),
    )


def charge_list(company_number: str, raw: JSON, start_index: int, outstanding_only: bool) -> ChargeList:
    items = _items(raw.get("items"))
    charges = [_charge(i) for i in items]
    total = _int(raw.get("total_count"), len(items))
    satisfied = _int(raw.get("satisfied_count"))
    if outstanding_only:
        charges = [c for c in charges if c.status in ("outstanding", "part-satisfied")]
    return ChargeList(
        company_number=company_number,
        total=total,
        outstanding=max(0, total - satisfied),
        satisfied=satisfied,
        charges=charges,
        next_start_index=next_start(start_index, len(items), total),
    )


# -- registered office -------------------------------------------------------


_ADDRESS_FORMS = {"AD01", "AD02", "AD03", "AD04", "287", "LLAD01", "NI 295"}


def registered_office_history(company_number: str, current: JSON, filings: JSON) -> RegisteredOfficeHistory:
    items = _items(filings.get("items"))
    changes = []
    for i in items:
        values = _obj(i.get("description_values"))
        form = i.get("type")
        is_change = form in _ADDRESS_FORMS or "change-registered-office-address" in str(i.get("description", ""))
        if not is_change:
            continue
        changes.append(
            AddressChange(
                changed_on=_d(values.get("change_date")) or _d(i.get("action_date")) or _d(i.get("date")),
                filed_on=_d(i.get("date")),
                old_address=values.get("old_address"),
                new_address=values.get("new_address"),
                form=form,
            )
        )
    total = _int(filings.get("total_count"), len(items))
    return RegisteredOfficeHistory(
        company_number=company_number,
        current_address=one_line_address(current),
        changes=changes,
        complete=len(items) >= total,
    )


# -- PSCs --------------------------------------------------------------------


def _psc_kind(kind: str) -> PscKind:
    for prefix, name in (
        ("individual", "individual"),
        ("corporate-entity", "corporate entity"),
        ("legal-person", "legal person"),
        ("super-secure", "super-secure"),
    ):
        if kind.startswith(prefix):
            return name  # type: ignore[return-value]
    return "other"


def _psc(i: JSON) -> PersonWithSignificantControl:
    kind = str(i.get("kind") or "")
    ident = _obj(i.get("identification"))
    return PersonWithSignificantControl(
        name=i.get("name"),
        kind=_psc_kind(kind),
        beneficial_owner=kind.endswith("beneficial-owner"),
        notified_on=_d(i.get("notified_on")),
        ceased_on=_d(i.get("ceased_on")),
        control=[
            enums.label("psc_nature_of_control", n) or n
            for n in i.get("natures_of_control") or []
            if isinstance(n, str)
        ],
        nationality=i.get("nationality"),
        country_of_residence=i.get("country_of_residence"),
        born=year_month(i.get("date_of_birth")),
        registration_number=ident.get("registration_number"),
        place_registered=ident.get("place_registered") or ident.get("country_registered"),
        legal_form=ident.get("legal_form"),
    )


def psc_list(company_number: str, raw: JSON, start_index: int, include_ceased: bool) -> PscList:
    items = _items(raw.get("items"))
    people = []
    omitted = 0
    for i in items:
        if (i.get("ceased_on") or i.get("ceased")) and not include_ceased:
            omitted += 1
            continue
        people.append(_psc(i))
    total = _int(raw.get("total_results"), len(items))
    return PscList(
        company_number=company_number,
        active_count=_int(raw.get("active_count")),
        ceased_count=_int(raw.get("ceased_count")),
        people=people,
        ceased_omitted=omitted,
        next_start_index=next_start(start_index, len(items), total),
    )

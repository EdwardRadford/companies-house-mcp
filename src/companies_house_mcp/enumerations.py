"""Lookup of Companies House enumeration keys to the text their website shows.

Data is vendored from github.com/companieshouse/api-enumerations by
`scripts/sync_enumerations.py`; see that script for why.
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib import resources
from typing import Any

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_EMPTY_PARTS = re.compile(r"(?:\s*,)+")


@cache
def _tables() -> dict[str, dict[str, str]]:
    raw = resources.files(__package__).joinpath("data/enumerations.json").read_text(encoding="utf-8")
    return {k: v for k, v in json.loads(raw).items() if not k.startswith("_")}


def humanise(key: str) -> str:
    return key.replace("-", " ").replace("_", " ").strip().capitalize()


def label(table: str, key: str | None) -> str | None:
    """Text for `key` in `table`; a humanised key if Companies House added one we don't know."""
    if not key:
        return None
    text = _tables()[table].get(key)
    # The source tables mix en dashes and hyphens for the same separator.
    return text.replace("–", "-") if text else humanise(key)


def sic_description(code: str) -> str | None:
    return _tables()["sic_descriptions"].get(code)


def tidy_address(text: object) -> str | None:
    """Address strings in filing values arrive as ", Tesco House, Delamare Road,, Cheshunt,, Herts"."""
    if not isinstance(text, str):
        return None
    tidy = _EMPTY_PARTS.sub(",", text)
    tidy = re.sub(r",(?=\S)", ", ", tidy)
    tidy = re.sub(r"\s{2,}", " ", tidy).strip(" ,")
    return tidy or None


def _value(values: dict[str, Any], name: str) -> str:
    raw = values.get(name, "")
    if name.endswith("address"):
        return tidy_address(raw) or ""
    return str(raw).strip()


def filing_description(key: str | None, values: dict[str, Any] | None) -> str:
    """Render a filing-history description the way the register's website does.

    The API gives a key ("appoint-person-director-company-with-name-date") and
    a dict of values; the text lives in a template with {placeholders}.
    Legacy filings carry their free text in values["description"].
    """
    values = values or {}
    template = _tables()["filing_description"].get(key or "")
    if not template:
        fallback = values.get("description")
        return str(fallback) if fallback else humanise(key or "filing")
    text = _PLACEHOLDER.sub(lambda m: _value(values, m.group(1)), template)
    text = text.replace("**", "")
    return re.sub(r"\s{2,}", " ", text).strip().rstrip(",")

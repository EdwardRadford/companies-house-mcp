"""Company number normalisation.

Models produce company numbers in every shape a human would: "445790",
"sc 123456", "00445790 ", "No. 04 12 34 56". The register only accepts the
canonical 8-character form, and a malformed number sent upstream comes back
as a 404 that reads like "this company does not exist". Normalising here, and
refusing what cannot be normalised, keeps "you typed it wrong" distinct from
"it isn't there".
"""

from __future__ import annotations

import re

from .errors import InvalidCompanyNumber

# 8 digits (England & Wales), 2 letters + 6 digits (SC, NI, OC, SO, NC, LP,
# SL, FC, GE, ...), or R + 7 digits (old Northern Ireland register).
_CANONICAL = re.compile(r"^(?:\d{8}|[A-Z]{2}\d{6}|R\d{7})$")
_PREFIXED = re.compile(r"^([A-Z]{2})(\d{1,6})$")
_NOISE = re.compile(r"[\s.\-/]+")
_LABEL = re.compile(r"^(?:COMPANY\s*)?(?:NO|NUMBER|NUM)\.?\s*:?\s*", re.IGNORECASE)


def normalise_company_number(raw: str) -> str:
    """Return the canonical 8-character company number or raise InvalidCompanyNumber."""
    if not isinstance(raw, str):
        raise InvalidCompanyNumber(str(raw))
    text = _LABEL.sub("", raw.strip())
    text = _NOISE.sub("", text).upper()
    if text.isdigit() and 0 < len(text) <= 8:
        text = text.zfill(8)
    else:
        prefixed = _PREFIXED.match(text)
        if prefixed:
            text = prefixed.group(1) + prefixed.group(2).zfill(6)
    if not _CANONICAL.match(text) or text == "00000000":
        raise InvalidCompanyNumber(raw)
    return text

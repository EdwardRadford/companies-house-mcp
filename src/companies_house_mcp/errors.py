"""Failures a caller can act on.

Every error here carries a message written for the model that made the call:
what went wrong, and what to do next. The server turns them into MCP tool
errors verbatim. Anything else that escapes a tool is a bug, and the SDK
reports it as a generic crash without leaking internals.
"""

from __future__ import annotations


class CompaniesHouseError(Exception):
    """Base class. `str(err)` is the model-facing message."""


class InvalidCompanyNumber(CompaniesHouseError):
    def __init__(self, raw: str) -> None:
        self.raw = raw
        super().__init__(
            f"{raw!r} is not a valid UK company number. A company number is 8 characters: "
            "8 digits (e.g. 00445790, leading zeros may be left off) or a 2-letter prefix "
            "and 6 digits (e.g. SC123456 for Scotland, NI123456 for Northern Ireland, "
            "OC123456 for an LLP). If you only have the company's name, call "
            "search_companies first."
        )


class NotConfigured(CompaniesHouseError):
    def __init__(self) -> None:
        super().__init__(
            "The server has no Companies House API key, so it cannot reach the register. "
            "This is a server configuration problem, not something a retry will fix: the "
            "operator must set COMPANIES_HOUSE_API_KEY (a free key from "
            "https://developer.company-information.service.gov.uk/)."
        )


class AuthenticationFailed(CompaniesHouseError):
    def __init__(self) -> None:
        super().__init__(
            "Companies House rejected the server's API key (HTTP 401). This is a server "
            "configuration problem; retrying will not help. The operator should check "
            "COMPANIES_HOUSE_API_KEY is a REST API key, not a streaming key."
        )


class CompanyNotFound(CompaniesHouseError):
    def __init__(self, company_number: str) -> None:
        self.company_number = company_number
        super().__init__(
            f"No company with number {company_number} is on the Companies House register. "
            "Check the number, or call search_companies with the company's name to find it."
        )


class RateLimited(CompaniesHouseError):
    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = max(1, round(retry_after_seconds))
        super().__init__(
            "Companies House rate limit reached (600 requests per 5 minutes for this key). "
            f"Wait about {self.retry_after_seconds} seconds before calling again. Do not "
            "retry straight away: repeated calls extend the wait."
        )


class UpstreamUnavailable(CompaniesHouseError):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(
            f"The Companies House API is not responding properly ({detail}). The fault is "
            "on their side, not in the request. Try again in a minute; if it persists, "
            "tell the user the register is temporarily unavailable rather than guessing."
        )


class BadRequest(CompaniesHouseError):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Companies House refused the request as malformed: {detail}")

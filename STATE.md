# companies-house-mcp: state

## ED'S TO-DO
- [ ] Get a free Companies House API key: https://developer.company-information.service.gov.uk/
      → sign in → create an application (live environment) → create a REST key. Paste it to the
      session or store it in Bitwarden; Claude then records live fixtures and runs a live smoke test.
- [ ] Decide when and how it goes public (GitHub repo name, public or private, licence). The assistant session handles this with you.

Updated: 2026-09-23 (session ed-6f)

## Works (verified 23 Sep 2026)
- Seven read-only tools over MCP: search_companies, get_company_profile, list_officers, list_filings,
  list_charges, get_registered_office_history, list_persons_with_significant_control.
- 83 tests pass with no network and no key (1 skipped: live recordings, none yet). ruff and mypy --strict clean.
- Runs as a real stdio subprocess (`python -m companies_house_mcp` / `companies-house-mcp`); without a key it
  lists tools and every call returns a clear configuration error.

## Not yet verified
- Never run against the live API (no key). Fixtures are shaped from the published spec. Specific
  assumptions to confirm with a key: 404 for an empty charges/PSC resource; `particulars` object vs array;
  `description_values` keys for address changes; search `total_results` paging; 429 headers.

## Next (once the key exists)
1. `COMPANIES_HOUSE_API_KEY=... python scripts/record_fixtures.py 00445790 <a Scottish co> <an LLP> <a dissolved co>`,
   then `pytest` (test_recorded runs over them). Fix any drift.
2. Live smoke test through a real host: `claude mcp add companies-house -e COMPANIES_HOUSE_API_KEY=... -- companies-house-mcp`.
3. Optional polish for the portfolio: a short screen recording or transcript of a model answering "who owns X?" by following the PSC chain.

## Notes
- mcp SDK 2.2.0 renamed FastMCP to `mcp.server.mcpserver.MCPServer`; in-process test client is `mcp.Client(server)`.
- Lookup tables vendored from github.com/companieshouse/api-enumerations (the repo has no licence file); pulled 23 Sep 2026.

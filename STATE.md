# companies-house-mcp: state

## ED'S TO-DO
- [ ] Store the Companies House API key in Bitwarden (pasted into the ed-6f session on 23 Sep 2026; not in the repo or
      git history, verified). Regenerate it on the developer hub if you'd rather not keep one that sat in a transcript.

Updated: 2026-09-23 (session ed-6f)

## Live
- Public: https://github.com/EdwardRadford/companies-house-mcp (MIT). Published 23 Sep 2026 on Ed's approval in session.
  Verified logged out: repo page 200, raw README 200, GitHub detects MIT; anonymous clone has 0 key hits in tree and history.

## Works (verified 23 Sep 2026)
- Seven read-only tools over MCP: search_companies, get_company_profile, list_officers, list_filings,
  list_charges, get_registered_office_history, list_persons_with_significant_control.
- 127 tests pass offline: behaviour tests on synthetic fixtures plus 35 live recordings (5 companies, natural persons
  redacted). ruff, ruff format and mypy --strict clean. MIT LICENSE added (Ed approved, via ed-4f).
- Runs as a real stdio subprocess; wheel contains the enumeration data and entry point.
- Live smoke test through Claude Code headless (Sonnet, $0.13): followed Woolworths Limited -> Littlewoods Limited via the
  PSC chain, and correctly reported 00000001 as not on the register.

## What the live API contradicted (fixed; also in the README)
1. Lists for a company that does not exist return 200 + empty list (only the profile and ROA 404). Empty first pages are
   now confirmed against the profile.
2. Rate-limit header is X-Ratelimit-Remain, not X-Ratelimit-Remaining.
3. The "address" filing category includes AD02/AD03/353 (inspection location, register moves); ROA moves are now matched
   by description key. RP05 (moved to the Companies House default address) is flagged; the profile warns on it.
4. Address strings arrive with stray commas; tidied. Paper-era 287/LLP287 have free text only; kept in `description`.
Confirmed: charge particulars/classification/secured_details are objects; all filing keys seen are in the vendored tables.

## Next
1. Optional: a short transcript of a model answering "who ultimately owns X?" for the portfolio page.
2. Re-record occasionally: `COMPANIES_HOUSE_API_KEY=... python scripts/record_fixtures.py 00445790 SC535479 OC303675 00104206 06732228`.

## Notes
- mcp SDK 2.2.0 renamed FastMCP to `mcp.server.mcpserver.MCPServer`; in-process test client is `mcp.Client(server)`.
- Lookup tables vendored from github.com/companieshouse/api-enumerations (the repo has no licence file); pulled 23 Sep 2026.
- Recorded fixtures will be public with the repo: `scripts/record_fixtures.py` redacts natural persons; never bypass it.
- Shell heredocs through the Bash tool mangled backslashes and quotes twice this session; write patch scripts to the
  scratchpad and run them instead.

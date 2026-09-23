# companies-house-mcp: conventions and locked decisions

Read-only MCP server over the UK Companies House public data API. Built 23 Sep 2026 as a
portfolio piece for Ed's job applications (AI-adjacent roles; the FDE-style listings name
MCP servers as the deliverable). A hiring manager may read only the README, so the README
matters as much as the code.

State file: `STATE.md` (what works, Ed's to-do, next).

## Locked (do not relitigate without Ed)
- Seven read-only tools. No writes, ever. Every tool carries readOnly/idempotent/openWorld
  annotations, destructive false; `tests/test_surface.py` enforces it.
- Deliberately not exposed: officer search and officer appointments (person profiling),
  officer and PSC addresses, advanced search, document downloads, the streaming API. The
  README explains each; adding one is a decision for Ed, not a drive-by.
- Tool surface budget: 12,000 chars of names, descriptions and input schemas (test-enforced).
- Public on GitHub (EdwardRadford/companies-house-mcp, MIT) since 23 Sep 2026. No PyPI release without Ed.
- Recorded fixtures are public: `scripts/record_fixtures.py` redacts natural persons; never bypass it.

## Engineering
- Python 3.11+, `mcp` 2.x (`MCPServer`, not the v1 `FastMCP`), httpx, pydantic v2. Venv at `.venv`.
- `pytest` must pass with no network and no key. `ruff check .`, `ruff format`, `mypy` (strict) all clean before a commit.
- Layers: `client.py` (transport, errors) returns raw JSON; `shaping.py` (pure, total) makes models;
  `server.py` holds tools and their descriptions. Keep that split.
- Every expected failure is a `CompaniesHouseError` whose message is written for the model:
  what happened and what to do. Tools wrap calls in `_as_tool_errors()`.
- Enumerations are vendored: refresh with `python scripts/sync_enumerations.py` (needs pyyaml, dev extra).
- Fixtures in `tests/fixtures/` are synthetic and invented; never put a real person's data in them.
  Live recordings go in `tests/fixtures/recorded/` via `scripts/record_fixtures.py`.
- Commits: plain messages, no AI-attribution trailers.

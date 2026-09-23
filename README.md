# companies-house-mcp

An MCP server that gives a model read-only access to the UK Companies House register:
every company in England, Wales, Scotland and Northern Ireland, live or dissolved. With
it, a model can answer questions like "is this supplier still trading?", "who actually
owns this company?" and "has anyone lent money against it?" from the register itself,
not from memory.

Seven tools, all reads. Python, the official MCP SDK (`mcp` 2.x), `httpx`, `pydantic`.
Tested offline without an API key, and checked against the live register.

```
search_companies                       find a company by name, get its number
get_company_profile                    status, type, office, activities, deadlines, red flags
list_officers                          directors, secretaries, LLP members
list_filings                           what it has filed, in words
list_charges                           secured lending against it
get_registered_office_history          where it has been registered, and when it moved
list_persons_with_significant_control  who owns or controls it
```

Most of this README is about why the server looks the way it does. The decisions matter
more than the code: wrapping an API takes an afternoon; choosing what a model should see
is the actual work.

---

## Design decisions

### Seven tools, not thirty

The Companies House API has around thirty read endpoints. A server that mirrors them
one to one is easy to write and worse to use. Every tool's name, description and schema
sit in the model's context for the whole conversation, whether it is used or not. And
every extra tool is one more wrong choice on offer: tools that overlap ("search" and
"advanced search", "profile" and "registered office") are where models pick badly.

So the tools follow the questions people ask about a company, not the endpoints:

| Question | Tool | Upstream requests |
|---|---|---|
| Which company do you mean? | `search_companies` | 1 |
| What is it, and is it healthy? | `get_company_profile` | 1 |
| Who runs it? | `list_officers` | 1 (2 if the list is empty) |
| What has it filed? | `list_filings` | 1 (2 if the list is empty) |
| Who has security over it? | `list_charges` | 1 (2 if the list is empty) |
| Where has it been based? | `get_registered_office_history` | 2 |
| Who owns it? | `list_persons_with_significant_control` | 1 (2 if the list is empty) |

One tool, `get_registered_office_history`, has no endpoint of its own. Companies House
serves the current address and, separately, the filings that changed it. The model
wants the history, so the tool joins the two.

The whole tool surface (names, descriptions, input schemas) is under 8,000 characters,
roughly 2,000 tokens. `tests/test_surface.py` fails the build if it passes 12,000, so
any growth is a decision rather than drift.

### Every tool is a read, and says so

The public data API is read-only anyway; filing uses a separate API with per-company
authentication codes. But the server also tells the host so: each tool carries
`readOnlyHint`, `idempotentHint` and `openWorldHint`, and `destructiveHint: false`.
That matters in practice. A host can let the model run these tools without asking the
user each time, which a tool that could change the register would never earn. Mixing
reads and writes in one server makes the host treat all of it as the riskier kind.

### What is deliberately not exposed

- **Officer search and officer appointment history.** `/search/officers` and
  `/officers/{id}/appointments` turn a company tool into a person tool: "every company
  this person has ever been involved in". Due diligence has real uses for that, but it
  is a different risk profile, and it belongs in a separately reviewed server a host
  opts into, not bundled here.
- **Home and service addresses of officers and PSCs.** The API returns them. The
  models here do not. No company question needs a director's correspondence address.
- **Advanced search** (by activity code, incorporation date, location). It is useful
  for building lists of companies, but lists are not what this server is for, and it
  is the natural starting point for bulk harvesting.
- **Document downloads.** Accounts and forms are PDFs, often scans. Fetching them is a
  different job (size, OCR, caching) and would sit badly inside a quick lookup.
  `list_filings` says whether a document exists.
- **Lower-frequency resources:** insolvency case detail, disqualified officers,
  exemptions, UK establishments, statutory registers, PSC statements. Each is one
  small tool away when a real question needs it. The gap most likely to matter is PSC
  statements, so `list_persons_with_significant_control` says so: an empty list may
  mean the company filed a statement instead.
- **The streaming API.** It is push, not pull, and does not fit the request and
  response shape of a tool call.

### Results shaped for a model, not for a web page

The raw API is built for the Companies House website: nested address objects,
enumeration keys where words should be, links, etags, and many fields no answer needs.
A model pays for each of those tokens and then has to work out what they mean. So
every tool returns its own `pydantic` model, published as an MCP output schema, with:

- **Words, not codes.** `"ltd"` becomes "Private limited company"; a filing's
  `"appoint-person-director-company-with-name-date"` plus its values becomes
  "Appointment of Mr Tomasz Brandt as a director on 2019-11-04". The text comes from
  Companies House's own lookup tables ([api-enumerations](https://github.com/companieshouse/api-enumerations)),
  vendored as JSON by `scripts/sync_enumerations.py`, so it matches their website
  exactly. An unknown key degrades to readable words instead of disappearing.
- **Red flags derived, not left to inference.** `get_company_profile` returns a
  `warnings` list: overdue accounts, an overdue confirmation statement, liquidation,
  proposal to strike off, insolvency history, a disputed or undeliverable registered
  office. Without it, a model has to notice that one boolean among twenty is true. Its
  schema also says what an empty list means: none found, not "vetted".
- **Defaults that answer the usual question.** "Who are the directors?" means current
  ones, so resigned officers and ceased PSCs are left out unless asked for. The
  result still carries the whole-company counts and how many rows were dropped, so the
  model knows what it isn't seeing.
- **Paging the model can't get wrong.** Every list returns `next_start_index`, which is
  null at the end and never points past an empty page, so there is no loop to get stuck in.
- **Chains the model can follow.** A corporate owner comes back with its
  registration number, and the description says to pass it to `get_company_profile`.
  That is how "who ultimately owns this?" gets answered, one hop at a time.
- **Limits in the schema.** Page sizes are capped at 100 and filing categories are an
  enum, so a bad call fails validation before it costs a request against the key's
  quota.

Example: the profile of a company in trouble (from the test fixtures):

```json
{
  "company_number": "SC654321",
  "name": "NORTHGATE PLANT HIRE LTD",
  "status": "Liquidation",
  "registered_office": "c/o Firth & Mowat Recovery LLP, 3 Castle Wynd, Inverness, IV2 3EQ, Scotland",
  "warnings": [
    "Company status is Liquidation.",
    "Status detail: Active proposal to strike off.",
    "Accounts are overdue, due by 2025-12-02.",
    "Confirmation statement is overdue, due by 2025-03-15.",
    "The company has an insolvency history on the register.",
    "The registered office address is in dispute.",
    "Mail to the registered office has been returned as undeliverable."
  ]
}
```

### Inputs forgiving where it is safe, strict where it isn't

Models write company numbers the way people do: `445790`, `sc 123456`,
`Company No. 04 12 34 56`. All of those normalise to the canonical eight characters.
What cannot be a company number (`TESCO`, nine digits) is refused before any request,
with a message saying what a valid number looks like and to call `search_companies` if
all you have is a name. Sending it upstream would come back as a 404, and a model
reads a 404 as "this company does not exist". That is a different and wrong answer.

### Errors written for the model that has to handle them

Every expected failure reaches the model as a message that says what happened and what
to do next:

| Situation | What the model is told |
|---|---|
| Malformed number | what a valid one looks like; use `search_companies` |
| No such company | the number isn't on the register; search by name |
| Rate limited | wait about N seconds; don't retry straight away |
| API down or timing out | the fault is upstream; try again in a minute, don't guess |
| No key / bad key | server misconfigured; retrying won't help |

Unexpected exceptions are not dressed up: the SDK reports them as a generic tool
failure and nothing internal leaks into the conversation.

One case needs special handling, and the live API is what showed it (see below). Ask
Companies House for the charges, officers, filings or PSCs of a company that does not
exist and it answers 200 with an empty list. To a model that reads as "this company has
no charges", which is the wrong answer to a question about a company that isn't there.
So an empty first page is checked against the company profile, which does 404 for a
missing company: if the company exists the empty list stands; if not, the model gets
`CompanyNotFound`. The extra request is spent only when the answer is empty.

### Rate limiting that neither hangs nor hammers

The API allows 600 requests per five minutes per key, and a model fanning out across
twenty search results can hit that in seconds. The limiter keeps a rolling window of
its own requests. A short wait (up to 5 seconds) is absorbed quietly. A long wait is
refused at once with the real number of seconds, because a tool call that hangs for four
minutes is worse for an agent than an error it can plan around. The limiter also reads
the server's `X-Ratelimit-Remain` / `X-Ratelimit-Reset` headers, so it stays honest
when another process shares the key. Transient failures (502, 503, 504, connection
errors, timeouts) get exactly one retry; a 500 does not, because a request that broke
the server once will break it again.

### Built against the spec, then run against the real thing

The first version was written and tested against the published specification only,
before an API key existed. Then it was run against the live register: five companies
recorded (Tesco PLC, Deloitte LLP, Woolworths Limited, the old Woolworths company now
in liquidation, and a dissolved Scottish company), 35 responses in all. Here is what
the live API contradicted, and what it confirmed.

| Assumption from the spec | What the live API does | Consequence, and the fix |
|---|---|---|
| A company that doesn't exist gets a 404 | Only on the profile. Its charges, officers, filings and PSCs come back 200 with an empty list | The server would have told a model a non-existent company "has no charges". Empty lists are now confirmed against the profile |
| The rate-limit header is `X-Ratelimit-Remaining` | It is `X-Ratelimit-Remain` (with `-Limit: 600`, `-Window: 5m`, `-Reset`) | The limiter never saw the server's count. It reads the real header now, and the test fixtures use it |
| Filings in the `address` category are registered-office moves | The category also holds register inspection address changes (AD02), register moves (AD03) and register-of-members locations (353) | Tesco's history showed inspection-address changes as office moves. Office moves are now matched by description key, from the register's own tables |
| Office changes are AD01 forms | Companies House can move an office itself, to its default address in Cardiff (RP05), when the real one is shown to be wrong | That is a red flag, so it is flagged in the history, and the profile warns when the current office is the default address |
| Address values are clean text | They arrive as `, Tesco House, Delamare Road,, Cheshunt,, Herts` | Tidied before a model sees them |
| Old changes have old and new addresses | Paper-era forms (287, LLP287) carry only free text | Kept, with the text in `description` and the address fields left null |

Confirmed as assumed: charge `particulars`, `classification` and `secured_details`
arrive as objects, not the arrays the spec describes (the shaping already accepted
both); every filing description key across the five histories was found in the
vendored tables; an empty search is 200 with `total_results: 0`.

Last, a live run through a real host. Claude Code, with only this server connected,
was asked who owns the active Woolworths Limited and whether company 00000001 has any
charges. It called `search_companies`, then `list_persons_with_significant_control` and
`list_charges` in parallel, then `get_company_profile`. It answered that Woolworths
Limited is controlled by Littlewoods Limited (active, 00262152) and that 00000001 is not
on the register. Before the fix above, it would have said 00000001 had no charges.

---

## Using it

You need Python 3.11+ and a free API key from the
[Companies House developer hub](https://developer.company-information.service.gov.uk/)
(create an application, then a REST key).

```bash
git clone <this repo> && cd companies-house-mcp
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
```

**Claude Code**

```bash
claude mcp add companies-house -e COMPANIES_HOUSE_API_KEY=your-key -- companies-house-mcp
```

**Claude Desktop** (or any host that takes this config shape)

```json
{
  "mcpServers": {
    "companies-house": {
      "command": "/path/to/.venv/bin/companies-house-mcp",
      "env": { "COMPANIES_HOUSE_API_KEY": "your-key" }
    }
  }
}
```

It runs over stdio by default. `companies-house-mcp --transport streamable-http --port 8000`
serves it over HTTP instead. Without a key the server still starts and lists its tools,
and every call explains that the key is missing.

| Variable | Default | |
|---|---|---|
| `COMPANIES_HOUSE_API_KEY` | none | required for calls |
| `COMPANIES_HOUSE_BASE_URL` | the live API | e.g. a sandbox |
| `COMPANIES_HOUSE_TIMEOUT` | `10` | seconds per request |

## Tests

```bash
pip install -e ".[dev]"
pytest            # no network, no key
ruff check . && mypy
```

The suite fakes Companies House at the HTTP layer (`httpx.MockTransport`), so the real
client, limiter, retry and error mapping run in every test. Tool tests talk to the
server through the SDK's in-process MCP client, the same path a host takes, and one test
starts the server as a subprocess over stdio. That one catches packaging mistakes and
stray output that would corrupt the protocol stream. `test_surface.py` checks the
contract itself: exactly these seven tools, all annotated read-only, every input
documented, page sizes capped, and the context budget.

There are two kinds of fixture. The synthetic ones (invented companies, shaped on the
published spec, with the live API's behaviour folded back in) drive the behaviour
tests. The recorded ones in `tests/fixtures/recorded/` are real responses from the
live register, made by `scripts/record_fixtures.py`, and `tests/test_recorded.py` runs
the shaping layer over every one, so drift in the live API shows up as a failing test.
Before a recording is written, natural persons are redacted: individual officers' and
PSCs' names, birth dates, addresses and officer ids, and officer names inside filing
text. The server never returns officers' addresses, and its fixtures don't publish
them either. Companies and corporate officers are kept as recorded.

## Layout

```
src/companies_house_mcp/
  server.py          tools, descriptions, argument schemas, entry point
  client.py          HTTP: auth, retries, status codes to errors, the empty-list check
  ratelimit.py       sliding-window limiter that also obeys the server's headers
  models.py          what the tools return (the output schemas)
  shaping.py         raw API JSON to those models; total, never throws on odd records
  company_number.py  normalisation and validation
  errors.py          every expected failure, with its model-facing message
  enumerations.py    Companies House lookup tables (data/enumerations.json)
scripts/             refresh the lookup tables; record live fixtures
tests/               fake API, tool tests over MCP, stdio test, surface contract
```

## Notes

- The register holds what companies filed. It is authoritative for what was filed and
  when, not proof that the contents are true. The server's instructions tell the model
  as much.
- Register data comes from Companies House and is subject to their terms. The vendored
  lookup tables come from `companieshouse/api-enumerations`.

## Licence

MIT. See `LICENSE`.

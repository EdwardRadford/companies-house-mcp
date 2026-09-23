# Fixtures

Synthetic responses shaped field for field on the published Companies House API
specification (developer-specs.company-information.service.gov.uk), covering both shapes
where the spec is ambiguous (`particulars` and `classification` as an object or an
array). The companies, people and numbers are invented.

Where the live API turned out to differ from the spec (checked 23 Sep 2026), the
synthetic fixtures and the fake in `conftest.py` follow the live behaviour: empty lists
for a company that doesn't exist, the `X-Ratelimit-Remain` header, and address filings
that are not registered-office moves.

`recorded/` holds real responses from the live register, made by
`scripts/record_fixtures.py` with natural persons redacted. `tests/test_recorded.py`
runs the shaping layer over all of them.

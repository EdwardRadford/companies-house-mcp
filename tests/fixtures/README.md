# Fixtures

Synthetic responses shaped field for field on the published Companies House API
specification (developer-specs.company-information.service.gov.uk), covering both shapes
where the spec is ambiguous (`particulars` and `classification` as an object or an
array). The companies, people and numbers are invented.

`scripts/record_fixtures.py` records real responses into `tests/fixtures/recorded/`
once an API key is set, and `tests/test_recorded.py` runs the shaping layer over
whatever is there.

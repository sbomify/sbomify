# CSAF 2.0 schemas

Vendored copies of the schemas the advisory tests validate a rendered CSAF
document against. They are test fixtures, not something the app serves.

| File | Source | Retrieved |
| --- | --- | --- |
| `csaf_json_schema.json` | <https://docs.oasis-open.org/csaf/csaf/v2.0/csaf_json_schema.json> | 2026-09-03 |
| `cvss-v2.0.json` | <https://www.first.org/cvss/cvss-v2.0.json> | 2026-09-03 |
| `cvss-v3.0.json` | <https://www.first.org/cvss/cvss-v3.0.json> | 2026-09-03 |
| `cvss-v3.1.json` | <https://www.first.org/cvss/cvss-v3.1.json> | 2026-09-03 |

The CSAF schema refers to the three CVSS schemas by URL. The tests register
all four in a local `referencing` registry so validation never touches the
network. Re-format with `python -m json.tool --indent 2` when refreshing.

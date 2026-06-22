# VEX — justifications for irreducible vulnerabilities

CycloneDX VEX (Vulnerability Exploitability eXchange) documents that justify the
High/Critical advisories in sbomify's own components that **cannot** be removed by
a version bump, so the dashboard reflects *unaddressed* risk only (issue #1020,
Workstream 5).

Each statement is `analysis.state = not_affected` with a CycloneDX justification
(`code_not_present`, `code_not_reachable`, `requires_environment`, …) and a
`detail` explaining why sbomify is not exploitable, plus a `response` of `update`
where an upstream fix is expected.

| File | Component | Residual | Justification |
| --- | --- | --- | --- |
| `frontend-stack.vex.cdx.json` | Frontend Stack (`bun.lock`) | `serialize-javascript@6.0.2` (GHSA-5c6j-r48x-rmvq) | `code_not_present` — build-time-only minifier dep, not shipped to the browser bundle. 6.x stays resolved because `workbox-build@7.4.0` still pins the `@rollup/plugin-terser` 0.4.x line (which caps serialize-javascript at `^6.0.1`); `@rollup/plugin-terser` 1.0.0+ moves to `^7.0.3` but isn't reachable until workbox-build updates. |
| `container.vex.cdx.json` | Container image | `CVE-2026-34040` (Moby AuthZ bypass), `CVE-2026-41567` (archive-copy in-container decompressor exec), `CVE-2026-42306` (`docker cp` TOCTOU mount redirect) in the **osv-scanner** binary's indirect `github.com/docker/docker` dep | `code_not_reachable` — all three are Docker **daemon** code paths; osv-scanner is a client/scanner run against SBOM/lockfile inputs and never starts a daemon. |
| `container.vex.cdx.json` | Container image | Go-stdlib `CVE-2026-42504` (`mime.WordDecoder.DecodeHeader` quadratic-complexity DoS) in the **cosign** binary | `code_not_reachable` — the RFC 2047 email encoded-word decoder is not on cosign's HTTP+JSON path to the registry/Rekor/Fulcio. cosign v3.1.1 (Go 1.26.3) is the latest release; fixed by Go 1.26.4+. |

## How these are applied

sbomify scans its own SBOMs via Dependency-Track. To suppress a justified
finding from the workspace dashboard, upload the relevant VEX document to its
component (Python Stack / Frontend Stack / Container) so DT records the
`not_affected` analysis. These files are the canonical, version-controlled source
of those justifications; re-upload them whenever a residual changes.

The Python Stack carries no VEX: its residuals are remediated by version bumps in
`uv.lock` (see #1020).

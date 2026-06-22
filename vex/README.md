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
| `frontend-stack.vex.cdx.json` | Frontend Stack (`bun.lock`) | `serialize-javascript@6.0.2` (GHSA-5c6j-r48x-rmvq) | `code_not_present` — build-time-only minifier dep (`@rollup/plugin-terser` pins `^6.0.1`), not shipped to the browser bundle; 7.0.3 breaks `vite build` (calls `crypto.randomUUID()` at load). |
| `container.vex.cdx.json` | Container image | 3× `github.com/docker/docker` High in the **osv-scanner** binary | `code_not_reachable` — osv-scanner is run against SBOM/lockfile inputs, never a Docker daemon. |
| `container.vex.cdx.json` | Container image | Go-stdlib `CVE-2026-42504` MIME DoS in the **cosign** binary | `requires_environment` — cosign contacts only trusted sigstore/OCI endpoints; cosign v3.1.1 is the latest release (built on Go 1.26.3). |

## How these are applied

sbomify scans its own SBOMs via Dependency-Track. To suppress a justified
finding from the workspace dashboard, upload the relevant VEX document to its
component (Python Stack / Frontend Stack / Container) so DT records the
`not_affected` analysis. These files are the canonical, version-controlled source
of those justifications; re-upload them whenever a residual changes.

The Python Stack carries no VEX: its residuals are remediated by version bumps in
`uv.lock` (see #1020).

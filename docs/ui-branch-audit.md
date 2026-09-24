# UI branch audit — 24 September 2026

Reviewed the UI migration against `master`, including template inheritance,
component callers, client registration, form contracts, shared styles and the
services supplying the new dashboard and inventory. The source inventory covered
508 tracked templates, including 208 Cotton components, before this cleanup.

## Findings and fixes

| Finding | Effect | Resolution |
| --- | --- | --- |
| [Three toast surfaces](../sbomify/templates/components/feedback/toast_container.html) and separate full-page/HTMX message handlers | Styling drift; repeated listeners; public pages had no toast destination. | Static and live notifications compose `feedback/toast.html`. Both application shells render its container and initialize one message consumer after Alpine starts. |
| [Broken template syntax inside the full-page message script](../sbomify/apps/core/templates/core/components/messages.html.j2) | A response carrying a Django message could emit invalid JavaScript instead of displaying feedback. | Messages render as escaped text, consumed once by `django-messages.ts`. No inline script generation or asset import per message. |
| [Pipe/colon splitting in the old message consumer](../sbomify/apps/core/js/django-messages.ts) | Ordinary punctuation truncated or split a message. | Read each message's text content independently. Browser coverage includes punctuation and literal HTML, initial requests and repeated HTMX navigation. |
| [Fixed minimum toast width](../sbomify/templates/components/feedback/toast.html) | Notifications could exceed a narrow viewport; long identifiers could overflow. | Bound width to the viewport and wrap message text. Verify one dismissible notification at 320px and desktop widths. |
| [White text over arbitrary public branding](../sbomify/apps/core/templates/core/component_details_public_base.html.j2) | Pale workspace colours made access and download buttons unreadable. | Public access, signing and artifact download controls use neutral secondary buttons. Browser checks verify contrast for pale and dark accents. |
| [Separate support](../sbomify/apps/core/templates/core/support_contact.html.j2), checkout and access-form layouts | Duplicate headings, labels and notices; inconsistent spacing; narrow-screen actions could overflow. | Compose existing frames, headings, cards/surfaces, fields and alerts. Preserve form actions, CSRF, field names, validation, signature consent and Turnstile callbacks. |
| Missing skip-link targets on standalone pages | Keyboard users could activate a link without reaching the main content. | Standalone support, checkout, error and workspace-availability pages expose `main-content`. |
| [A second token-creation form on Settings](../sbomify/apps/core/templates/core/settings.html.j2) without a selected workspace | Choice fields appeared as text boxes, and submitting could only return an error because creation requires a workspace. | Remove the unusable form and unreachable token-result card. Link to workspace selection, which leads to the existing scope and expiry controls. Keep invitation handling and existing-token management. |
| [Zero-day patch targets](../sbomify/apps/core/services/security_snapshot.py) accepted by Settings but ignored by calculations | A stricter target appeared as “Best effort”, hiding breaches from dashboard and KPI totals. | Treat zero as a deadline and only `None` as no target. Extend existing dashboard and KPI regressions with zero-day policies. |
| [Unmocked artifact reads in the vulnerability browser fixture](../sbomify/apps/core/tests/e2e/test_sbom_vulnerabilities.py) | Pagination could render correctly while the test timed out waiting for an unrelated crypto-inventory request. | Model the fixture's missing artifact in its shared setup. Holding the crypto request open reproduced the failure; the fix removes the storage dependency without changing assertions. |
| [Immediate layout assertion after resizing](../sbomify/apps/core/tests/e2e/test_shared_ui_refinements.py) | The tab test could read transient overflow before the responsive layout settled. | Wait for the same zero-overflow condition. The original failure reproduced on the fifth repetition and had already settled by the diagnostic; the revised check passed 40 repetitions across both themes. |

## Removed duplication

- Remove 25 superseded or unused templates: former dashboard panels, assignment
  and visibility controls, public card wrappers, controls-catalog prototypes,
  obsolete plan selection, a second workspace selector and old message shells.
- Remove six unused Alpine controllers and their six dedicated test files:
  assignment manager, generic item list, plan card, public-status toggle, release
  list and assessment badge. Their replacement interactions remain covered by
  the live feature suites. Move the scan-count copy regression to the active
  assessment template.
- Remove the two stylesheets owned solely by those deleted controls. Preserve
  the legacy `tw-*` stylesheet used by remaining consumers.
- Remove duplicate SBOM and workspace bundle registrations already performed by the central
  Alpine initializer, and unused public theme-switching JavaScript.
- Retain the old toast include as a one-line compatibility adapter, with no
  second implementation.

## Layout review

The app shell, public workspace shell, authentication shell and email layouts
serve different audiences and remain distinct. App pages continue to share
`layout/frame` and `layout/page_header`; public forms now compose the branded
headings and surfaces with ordinary form controls. Distinct controls such as
tabs, steppers, dialogs and native inputs have not been merged merely because
they look similar.

The browser header contract compares 30 app destinations at mobile and desktop
widths. The complete browser suite also exercises public pages, settings,
onboarding, inventories, assessments, dialogs, loading states and navigation.
Support, checkout, Settings and access-form screenshots were reviewed at 375,
576, 992 and 1920 pixels; the public download comparisons were reviewed at 375
and 576 pixels. Source inspection and automated route coverage do not exercise
every permission and data combination manually.

## Validation

- All 16 backend CI groups in Docker, using CI's separate synchronous and
  asynchronous selections: **10,152 passed, 9 distinct cases skipped**.
- Frontend: **595 passed**, plus ESLint and the production asset build.
- All pre-commit hooks passed, including TypeScript, Ruff, mypy, Bandit,
  template formatting/lint and Markdown checks.
- Keycloak theme build, migration consistency, Caddy validation/formatting,
  the production `linux/amd64` Docker build and Docker context exclusions passed.
- Final complete sequential browser run: **492 passed, 32 existing manual
  screenshot-generator cases skipped**, with zero failures or errors. CI's
  separate asynchronous selection contains no browser tests.
- Reviewed and updated 34 baseline images for the intentional layout changes.
  Screenshot tolerances stayed at 0.5%, and no checks were disabled.
- Full browser reruns exposed the storage-fixture and resize timing failures
  described above. Their owning suites passed after the fixes, followed by the
  clean complete run. An earlier mobile workspace-menu timeout passed its owning
  suite and all three subsequent full runs; that assertion and menu were unchanged.

These are local results. Changes have not been pushed, so they do not represent
GitHub CI results. Hosted CodeQL and OpenGrep scans were not run locally.

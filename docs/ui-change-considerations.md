# UI change considerations and CI

The UI migration exposed application regressions, outdated test expectations and
test-environment failures. They need different fixes. These considerations explain
what failed and which checks to inspect before another UI change.

The design rules remain in [AGENTS.md](../AGENTS.md#frontend-ui), also read through
the `CLAUDE.md` symlink. Component files and `/design-system/` define the visual
recipes. This guide covers validation, not a second component library.

## Failures exposed by the migration

| Change or failure | Consideration for future changes | Relevant code and tests |
| --- | --- | --- |
| Assessment badges gained `aria-hidden` on decorative icons. An SBOM test matched the entire old icon HTML and failed although the displayed status was correct. | Keep the accessibility improvement. Assert the heading's displayed status, scoped so a nested badge or a zero-count chip cannot satisfy the test. Search outside the edited app: the template was in Plugins, its page in Core, and this test in SBOMs. | [Skipped versus pending](../sbomify/apps/sboms/tests/test_nothing_scanned_state.py), [per-run assessment badges](../sbomify/apps/plugins/tests/test_assessment_run_item_badge.py), [artifact scan page](../sbomify/apps/core/tests/test_artifact_scan_card.py). |
| Shared pagination replaced `Page 1 / 12` copy and an old `vuln_next_url` context value. Tests still expected the old implementation. | Follow the rendered Next page link and verify page boundaries, retained filters and page size. Preserve `aria-current` and accessible control names. A copy update must not weaken coverage of which vulnerabilities are reachable. | [Artifact pagination](../sbomify/apps/core/tests/test_artifact_scan_card.py), [panel pagination and triage](../sbomify/apps/core/tests/test_panel_triage_and_page_size.py), [finding controls in the browser](../sbomify/apps/core/tests/e2e/test_sbom_vulnerabilities.py). |
| Components became a view within Products. A critical-path check still expected the old document title. | Check browser titles, headings, navigation labels and accessible names when moving or renaming a page. Keep existing routes and deep links working; update the corresponding expectations in the same change. | [Critical paths](../sbomify/apps/core/tests/e2e/test_critical_paths.py), [shared page headers](../sbomify/apps/core/tests/e2e/test_page_headers.py), [repaired navigation and actions](../sbomify/apps/core/tests/e2e/test_ui_action_repairs.py). |
| Fixed tables used `overflow-wrap:anywhere`, which let short badges and flex content shrink below their word width. | A screenshot difference can be a real regression. Inspect long identifiers and short labels together on narrow screens. Fix the shared table recipe before refreshing baselines; preserve sort widths and scroll position. | [Table component](../sbomify/templates/components/tables/table.html), [table contracts](../sbomify/apps/core/tests/test_cotton_tables.py), [mobile layout](../sbomify/apps/core/tests/e2e/test_mobile_layout.py). |
| Shared chrome, headers, frames, cards, forms, loaders and modal spacing changed existing page screenshots. Later checks still found stale document and trusted-publisher mobile baselines. | Trace every consumer of a shared change, including public pages and open dialogs. Review each affected width and theme, including intermediate widths such as 576 and 992. Update only intentional visual differences and rerun against the reviewed baselines. | [Browser suite](../sbomify/apps/core/tests/e2e/), [stored baselines](../sbomify/apps/core/tests/e2e/__snapshots__/), [comparison tolerance and capture code](../sbomify/apps/core/tests/e2e/utils.py). |
| Development builds could see Controls sources, but the production Docker build did not copy its JavaScript or the Controls/OIDC templates. | New imports and Tailwind classes must reach the production build context. Check Vite entry points, Tailwind source scanning, Docker copies and ignore rules together. A successful local Vite build does not prove the Docker build works. | [Dockerfile](../Dockerfile), [Vite entries](../vite.config.ts), [Tailwind sources](../sbomify/assets/css/tailwind.src.css), [Docker ignore rules](../.dockerignore). |
| Public-page navigation work was followed by CodeQL findings in custom-domain redirects and weak hostname assertions. | UI work can cross a security boundary. Reuse the validated redirect helper, retain workspace permissions, and compare complete allowed hosts and schemes. Test the displayed DNS target exactly rather than finding a hostname substring anywhere in a response. | [Redirect guard](../sbomify/apps/core/url_utils.py), [redirect tests](../sbomify/apps/core/tests/test_url_utils.py), [custom-domain UI tests](../sbomify/apps/teams/tests/test_custom_domain_ui.py), [CodeQL workflow](../.github/workflows/codeql.yml). |

## Related local failures that affect confidence in CI

These problems appeared during local validation and cleanup. Do not describe them
all as design regressions in GitHub CI.

- **Ambiguous selectors and readiness.** Shared forms introduced several controls
  whose names contained "Product". Use exact accessible names and scope controls
  to their form, table or dialog. Parties navigation also needed to wait for the
  actual Alpine-controlled content before clicking. Use observable readiness,
  not a force-click or an arbitrary delay. See [dashboard interactions](../sbomify/apps/core/tests/e2e/test_dashboard.py)
  and [action repairs](../sbomify/apps/core/tests/e2e/test_ui_action_repairs.py).
- **Fixture scope and environment-dependent copy.** Plan tests shared priced-plan
  data through a test module, and upload screenshots inherited a local upload-size
  setting. Keep reusable data in [fixtures.py](../sbomify/apps/core/tests/e2e/fixtures.py),
  with isolated sessions in [conftest.py](../sbomify/apps/core/tests/e2e/conftest.py).
  Pin the settings, prices and dates that the test renders. Confirm a test file
  works alone and in the wider suite; do not make production defaults match one
  machine's screenshot.
- **Shared browser state.** Parallel browser runs interfered with focus and
  reduced-motion settings during loading-state checks. Run E2E tests sequentially
  against the shared CDP browser. Exercise both skeletons and the content that
  replaces them, including public stylesheets. See [loading-state tests](../sbomify/apps/core/tests/e2e/test_loading_states.py).
- **Dismissal can overtake queued focus.** Header menus could steal focus back
  after Escape because their opening callback ran during the closing transition.
  Check the current open state inside the deferred callback and focus directly;
  Alpine's `$focus.focus()` schedules another callback beyond that check. Test
  dismissal during opening with both motion preferences. See [header controls](../sbomify/apps/core/tests/e2e/test_chrome_controls.py).
- **Bundle startup order.** The empty dashboard loads an upload bundle that can
  start Alpine before the main bundle. Register shared components in
  [the central initializer](../sbomify/apps/core/js/alpine-init.ts), before
  `Alpine.start()`. A missing search controller left its panel open and empty.
  Exercise pages with conditional bundles, including a brand-new workspace;
  [search browser tests](../sbomify/apps/core/tests/e2e/test_navbar_search.py) cover
  that state as well as focus, suggestions, keyboard navigation and dismissal.
- **Formatting and static checks.** Template and Python formatter output was
  needed during the migration. Run the actual [pre-commit checks](../.pre-commit-config.yaml)
  before committing and review their diff. A browser render does not check
  formatting, types, template conventions or security rules.

## Where CI checks UI changes

Read the current [CI workflow](../.github/workflows/ci-cd.yml) instead of relying on
an old passing test count. It runs app backend groups, frontend tests, browser
tests, code quality and a production Docker build. The backend groups run sync
and async tests separately; reproduce the failing invocation when diagnosing an
order- or group-dependent failure. [The matrix check](../bin/check_ci_test_matrix.py)
keeps app test directories represented in CI. Security checks also live in the
[CodeQL](../.github/workflows/codeql.yml) and [OpenGrep](../.github/workflows/opengrep.yaml) workflows.

| Layer | Start here |
| --- | --- |
| Shared component markup, variants, state and accessibility | `test_cotton_*.py` in [Core tests](../sbomify/apps/core/tests/), [gallery view tests](../sbomify/apps/core/tests/test_design_system_view.py) and [gallery template](../sbomify/apps/core/templates/core/design_system.html.j2). |
| Server-rendered pages, permissions and HTMX fragments | Each affected app's `tests/` directory in the CI matrix. Trace includes across Core, SBOMs, Plugins, Teams and other consumers instead of selecting tests by the edited file's directory alone. |
| Client behavior, filters, keyboard handling, themes and chart lifetime | `*.spec.ts` beside the TypeScript source. Examples: [pagination](../sbomify/apps/core/js/components/pagination-controls.spec.ts), [themes](../sbomify/apps/core/js/theme-manager.spec.ts) and [charts](../sbomify/apps/vulnerability_scanning/js/vulnerability-chart.spec.ts). |
| User journeys and responsive layout | [E2E tests](../sbomify/apps/core/tests/e2e/), especially [headers](../sbomify/apps/core/tests/e2e/test_page_headers.py), [mobile](../sbomify/apps/core/tests/e2e/test_mobile_layout.py), [loading](../sbomify/apps/core/tests/e2e/test_loading_states.py), [actions](../sbomify/apps/core/tests/e2e/test_ui_action_repairs.py) and the changed page's snapshot tests. |

## Validation before committing UI changes

1. **Map the change.** Search callers, includes, old copy, selectors, IDs and
   context keys across the repository before editing. Include the design-system
   gallery, public pages, empty/error states and any HTMX replacement roots.
   Keep this inventory small and specific to the change.
2. **Check the contracts.** Preserve routes, authorization, form state, Alpine
   lifecycle, HTMX targets, sorting, focus and filter parameters. Tests should
   verify observable behavior; component contract tests may intentionally check
   exact classes or attributes. Change an expectation only after confirming the
   corresponding design change is intended. Do not delete assertions, add skips
   or loosen screenshot thresholds to turn a failure green.
3. **Choose sufficient scope.** Run the full backend suites of the affected apps,
   not just selected test functions. For shared components or templates spanning
   apps, run the full non-E2E backend suite. Run relevant frontend tests and the
   production asset build. Shared chrome, global styling and component recipes
   require the full browser suite; an isolated page change can use its complete
   page/interaction group and all affected snapshot variants. After a CI failure,
   reproduce it locally and run its complete owning suite before pushing a fix.
4. **Review visual evidence.** Build assets first. Use synthetic fixtures, inspect
   before/after images and fix clipping, unreadable text, unintended wrapping or
   missing controls before accepting snapshots. Keep responsive and theme variants
   together. Rerun the affected tests after updating baselines.
5. **Complete and report validation.** Use the [repository test and build commands](../AGENTS.md#build-and-development-commands)
   and run pre-commit checks. Run Django suites one at a time against the shared
   test services; parallel workers inside a backend run are supported, browser
   workers are not. Record the suites actually completed on the final change.
   Separate local results from the status of the newly pushed GitHub checks.

When adding source directories or changing build inputs, also run the production
Docker build. When changing public navigation or redirect helpers, include the
security checks and their regression tests. Documentation-only edits need Markdown
and link validation rather than another application test run.

## Diagnose infrastructure separately

The Plugins CI job once failed while pulling PostgreSQL because Docker Hub reset
the connection, before pytest started. A local full backend run also lost a worker;
the container recorded memory kills, and a rerun with four workers completed.
Neither result establishes a visual regression or a passing test run.

Read the failing job and step first. Retry a transient service download after
confirming the cause; reduce backend worker count when local Docker resources are
insufficient. A crashed worker or incomplete run still needs a completed rerun.
Use the [stale test database procedure](../AGENTS.md#testing) only after active test
runs finish. Never change UI code, skip a test or weaken assertions to compensate
for an infrastructure failure.

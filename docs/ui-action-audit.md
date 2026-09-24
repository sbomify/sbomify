# UI action audit

Audit date: 22 September 2026. Branch: `codex/prototype-chrome-homepage`.

Seven actionable issues were found. All seven are fixed in this branch. The original findings below are retained as an audit record, followed by the original coverage and integration limits.

## Completed fixes

| ID | Resolution |
| --- | --- |
| UI-01 | Identifier and link forms now use the shared HTMX response contract. Rejections preserve the card, dialog and entered values while showing the server error. The same correction also protects the lifecycle editor, including an unchanged save. |
| UI-02 | The CRA Parties shortcut opens the complete settings page. The embedded profile editor remains usable. |
| UI-03 | Settings has a Controls section and products have a Compliance controls section. Both compose one shared controls table. Catalog import, activation, deactivation, deletion, exports and product overrides are connected. Updates preserve the open category and refresh the correct catalog. Legacy links and Spotlight reach the restored destination. |
| UI-04 | The document uploader uses the existing modal and listens to the shared upload action. A persisted collapsed state no longer disables the shortcut. |
| UI-05 | Copy URL and badge actions use shared clipboard behavior outside the visibility administrator's scope. Visibility permissions are unchanged. |
| UI-06 | Both uploaders support `#upload-artifact`, the legacy `#upload-sbom` link, and the ordinary menu action. |
| UI-07 | Release rows and the artifact picker share URLs reversed by Django for documents, SBOMs, CBOMs and VEX. Public release rows do not use this private link builder. |

## Fix verification

- 219 backend tests passed for controls, catalog imports/exports, workspace boundaries, live permissions, settings navigation and Spotlight destinations.
- 703 JavaScript tests passed. The production frontend build, TypeScript compilation, Python type checking, changed-file linting and template checks passed.
- 88 Docker browser cases passed across the focused repairs, existing navigation workflows and affected page snapshots. These include 40 interaction cases and 48 page snapshot cases. The document upload interaction also captures the open dialog and checks its conditional fields.
- Browser cases cover rejected and successful identifier/link changes, a concurrent deletion, lifecycle saves, CRA-to-Parties navigation and return, catalog import and deletion, workspace defaults and product overrides, sharing across three roles, upload actions/deep links, and all four release artifact types.
- Reviewed and updated 12 existing baselines: eight product pages gain the Controls section and four document pages move uploading into the shared modal. The document baselines also catch up with the branch's existing chrome migration. Added four Controls snapshots across light/dark and desktop/mobile, plus the document dialog snapshot. Other passing baselines were retained.
- Test mutations used the isolated test database. External-service and legally meaningful workflows listed in the original audit remain separate integration checks.

## Original findings

P1 blocks access to a workflow or loses the form/error state. P2 is a disconnected shortcut with another way to reach the underlying function. This section describes the behavior before the fixes.

| ID | Priority | Page and action | Problem | Evidence |
| --- | --- | --- | --- | --- |
| UI-01 | P1 | Product details: identifier and link Add / Update / Delete | Rejected changes are treated as successful HTML replacements. The section can disappear without an error message. | Client/server response contracts traced; identifier rejection checked in an isolated browser fixture. |
| UI-02 | P1 | CRA assessment, step 1: **Edit in team settings** | Opens the contact-profile fragment as a standalone page, without the app shell or the parent needed by its controls. | Browser click in an isolated CRA fixture. |
| UI-03 | P1 | Settings and product details: compliance controls | Catalog management and product control overrides have no current page entry point. The old `#controls` destination opens General. | Call sites and routes traced; old destination checked in Chrome. |
| UI-04 | P2 | Document component: **Upload artifact…** | Dispatches the BOM upload event, but the document uploader does not listen for it. Nothing opens or expands. | Live Chrome click and source trace. |
| UI-05 | P2 | Component actions: **Copy public URL**, **Copy badge**, for a member | Menu items are shown to members, but their event handlers only exist inside the admin-only visibility selector. | Role-specific template trace and isolated member fixture. |
| UI-06 | P2 | Vulnerability trends empty state: **Upload your first SBOM** | Navigates to `#upload-sbom`, but the uploader now needs an event to open its modal. The hash leaves it closed. | Live Chrome destination check and source trace. |
| UI-07 | P2 | Release details: document name links, including the **Add artifact** picker | Builds `/component/.../document/.../`, which is not a registered route. Clicking a document name opens a 404 page. | Four broken targets found by the runtime link sweep, HTTP checks and a live Chrome click; picker uses the same incorrect pattern. |

### UI-01: Preserve rejected product changes and show the error

Open a product's **Product identifiers** section, choose **Add Identifier**, select PURL and enter a non-PURL value. The HTML required-field check accepts nonempty text, but the server rejects the identifier.

Both identifier and link cards use raw `fetch`, read every response as text, and assign it to the card's `outerHTML`. The view's `htmx_error_response` returns an empty body with the error in `HX-Trigger` and `HX-Reswap: none`. Raw fetch does not honour those headers. This affects create, update and delete error paths, not just the empty-state Add button.

The isolated identifier submission returned HTTP 200 with an empty body and `Invalid PURL format` in the trigger header. After the response, both the identifier card and dialog were absent. Link-card failure behaviour is source-confirmed through the same response contract; no link mutation was submitted live.

Source: [identifier forms](../sbomify/apps/core/templates/core/components/product_identifiers_card.html.j2), [link forms](../sbomify/apps/core/templates/core/components/product_links_card.html.j2), [identifier view](../sbomify/apps/core/views/product_identifiers.py), [link view](../sbomify/apps/core/views/product_links.py), [HTMX responses](../sbomify/apps/core/htmx.py).

- [x] Use the shared HTMX form/error contract, or explicitly handle the full response before replacing anything.
- [x] Keep the section, entered values and relevant dialog available after a rejection.
- [x] Check create/update/delete rejection and success for both sections. An HTTP status check alone is insufficient because these error responses currently use HTTP 200.

### UI-02: Link the CRA wizard to a full settings page

In CRA step 1, **Edit in team settings** links to `teams:contact_profiles_list`. That endpoint renders `profile_list.html.j2`, a partial intended to live inside `#contact-profiles-content`. Direct navigation removes the app shell and scripts. The subsequent contact-profile forms also expect that missing parent.

Source: [CRA step 1](../sbomify/apps/compliance/templates/compliance/cra_step_1.html.j2), [contact-profile views](../sbomify/apps/teams/views/contact_profiles.py), [profile list](../sbomify/apps/teams/templates/teams/contact_profiles/profile_list.html.j2), [profile form](../sbomify/apps/teams/templates/teams/contact_profiles/profile_form.html.j2).

- [x] Point full-page navigation to `teams:team_settings_tab` with `tab='contact-profiles'`.
- [x] Keep fragment endpoints for HTMX consumers and check other direct links to them.
- [x] From CRA, verify navigation to Parties, opening and cancelling a profile editor, and returning to the assessment.

### UI-03: Restore a reachable compliance-controls workflow

The controls library still has catalog activation, deactivation, import, deletion and status forms. However, `controls/settings_tab.html.j2` has no current caller, and `SETTINGS_TABS` has no controls entry. The private product page also does not mount `product_controls_section.html.j2`, although the controls view can still render it.

The product-controls fragment retains a **workspace-level status** link to workspace settings with `#controls`. Legacy settings helpers also preserve this fragment. Opening that destination shows General because the new settings navigation has no matching tab.

This is an orphaned workflow, rather than a currently visible inert button. CRA wizard controls do not provide the missing general catalog-management entry point.

Source: [settings registry](../sbomify/apps/teams/settings_tabs.py), [legacy settings destinations](../sbomify/apps/teams/utils.py), [settings navigation](../sbomify/apps/teams/js/settings-navigation.ts), [catalog management](../sbomify/apps/controls/templates/controls/settings_tab.html.j2), [product controls](../sbomify/apps/controls/templates/controls/components/product_controls_section.html.j2), [product composition](../sbomify/apps/core/templates/core/product_content.html.j2), [controls views](../sbomify/apps/controls/views.py).

- [x] Restore an agreed full-page destination using the shared components, or explicitly decide to retire this workflow.
- [x] Reconnect workspace catalog management and product overrides where appropriate.
- [x] Update legacy `#controls` destinations and add the restored destination to Spotlight.
- [x] Verify the same capability gates on the entry points and their forms.

### UI-04: Connect the document upload shortcut

On a document component, open **Component actions** and choose **Upload artifact…**. The menu closes, but there is no upload dialog or change to the inline upload section. For example, this is reproducible on `/component/YRHHjOd0fLlv/` in the seeded local workspace.

The inherited menu dispatches `open-upload`. The BOM uploader listens for that event; the document uploader instead manages a persisted `expanded` state and has no event listener. Its inline form remains a manual workaround.

Source: [shared component header](../sbomify/apps/core/templates/core/component_details_private_base.html.j2), [document detail composition](../sbomify/apps/core/templates/core/component_details_private_document.html.j2), [document uploader](../sbomify/apps/documents/templates/documents/components/document_upload.html.j2), [BOM uploader](../sbomify/apps/sboms/templates/sboms/components/sbom_upload.html.j2).

- [x] Connect the shared action to the document uploader's open/expand/focus behaviour.
- [x] Reuse the shared upload interaction contract rather than adding a document-only header implementation.
- [x] Verify menu opening, deep links and a stored collapsed state with the shared modal.

### UI-05: Make sharing independent of visibility administration

Public and gated components show **Copy public URL** and **Copy badge** to users who can manage components. This includes the `member` role. Their `copy-url` and `copy-badge` window listeners live solely on the visibility selector, which is included only for `can_administer`.

The result is a visible sharing action without a listener for ordinary members. Owner/admin coverage alone misses this. The shared header makes the gap apply to both BOM and document components.

In the isolated member fixture, both menu items were visible. Dispatching their click events produced zero clipboard calls, and neither sharing listener existed in the rendered page. Clipboard access was replaced with a test recorder; no live clipboard content was inspected.

Source: [component menu and permission gates](../sbomify/apps/core/templates/core/component_details_private_base.html.j2), [sharing listeners](../sbomify/apps/core/js/components/public-sharing.ts), [capability tiers](../sbomify/apps/core/authz.py).

- [x] Put sharing behaviour in a shared scope available wherever its menu items render.
- [x] Keep visibility changes restricted to the existing administration capability.
- [x] Verify both copy actions as member, admin and owner on public/gated components; keep them hidden on private components.

### UI-06: Give the upload CTA a supported deep link

The empty vulnerability-trends CTA links to the component detail page with `#upload-sbom`. The uploader's modal starts with `uploadOpen: false` and only opens on `open-upload`. The element ID exists, but there is no hash-to-modal behaviour. Opening `/component/GDc9Hn3A77nc/#upload-sbom` leaves the dialog closed.

Source: [trends empty-state CTA](../sbomify/apps/vulnerability_scanning/templates/vulnerability_scanning/components/_vulnerability_trends_results.html.j2), [BOM uploader](../sbomify/apps/sboms/templates/sboms/components/sbom_upload.html.j2).

- [x] Define one supported upload deep-link contract and use it for the CTA and uploader.
- [x] Verify direct navigation, a same-page hash change, and ordinary menu opening without creating duplicate modal behaviour.

### UI-07: Use real artifact routes in release links

On `/product/spwYAI4x6szs/release/AsIdKtce4XpL/`, clicking **Atlas security architecture** navigates to `/component/YRHHjOd0fLlv/document/N8zSduVosGYy/` and returns 404. The actual detail route is `/components/YRHHjOd0fLlv/documents/N8zSduVosGYy/`.

`getArtifactUrl` builds the invalid singular path for nested and flat document records. `getAvailableArtifactUrl` repeats it for document links inside the Add artifact picker. The runtime sweep found four distinct invalid document destinations across five rendered release rows. Other artifact types currently resolve or canonicalize; they should still be covered when replacing this link builder.

Source: [release artifact URL builders](../sbomify/apps/core/js/components/release-artifacts.ts), [release table and picker](../sbomify/apps/core/templates/core/components/release_artifacts.html.j2), [registered artifact routes](../sbomify/apps/core/urls.py).

- [x] Supply URLs resolved by Django for release artifact rows and picker records, following the application's shared navigation conventions.
- [x] Check document links in both the current collection and the available-artifact picker.
- [x] Verify SBOM, CBOM and VEX destinations through the same path, including any public consumer.

## Original audit coverage and evidence

The audit combined a route inventory, template/handler tracing, a browser sweep of seeded records, direct Chrome interaction, read-only HTTP destination checks and isolated browser fixtures. Page loading and finding a handler do not prove every submission succeeds.

- Inventoried 143 custom route patterns, including page routes, fragments, redirects and action endpoints. This is not 143 distinct screens.
- Collected 853 actionable template tags for wiring inspection. This is a source inventory, not a claim of 853 successful clicks.
- The browser sweep attempted 337 URLs across the local records, including anonymous Trust Center variants, fragments and an intentional missing-page check. It recorded 326 HTTP 200 responses, three expected access-denied responses, three expected 404 responses and five redirect/proxy failures that were investigated separately.
- The corrected browser sweep loaded the development JavaScript and recorded no uncaught page JavaScript errors. Disconnected event handlers can still be silent, as the findings above demonstrate.
- Resolved 991 distinct internal href targets after JavaScript initialized. Four document targets have no route (UI-07); the remaining unmatched raw path gains its valid trailing slash through Django's normal redirect.
- Checked 446 normalized internal GET destinations through Django, including artifact download variants. Queries for sorting/filtering were collapsed for this server check. Rendering a download response does not establish the contents of every downloaded file.
- Additional fixtures cover CRA wizard states, access requests/NDA forms, member permissions, billing/onboarding and rejected identifier input. Generated public VDP/declaration pages also rendered successfully with mocked document storage, and their back links opened the public product page.
- All 16 existing browser regressions for chrome menus, inventory navigation, product navigation and settings navigation passed in Docker. They cover desktop/mobile and light/dark variants, including selected saves, token creation/revocation, component assignment/removal and release editing in the isolated test database. Notification responses are mocked in the chrome test. No snapshots were regenerated.

The first navigation sweep could not reach the development asset server from the test browser. It was repeated with the correct asset routing; that first sweep is not interactive evidence. The corrected sweep's remaining redirect failures were a browser-proxy limitation, not reported as broken app destinations. Read-only server checks and targeted direct-browser/fixture checks were used to resolve them.

The [URL coverage inventory](ui-action-audit-pages.csv) records each sweep attempt. The [route inventory](ui-action-audit-routes.csv) includes redirects, partials and action endpoints so they are not silently counted as tested screens.

| Page family | Inspection performed | Result / outstanding boundary |
| --- | --- | --- |
| App chrome | Sidebar destinations, workspace/account/create menus, notifications wiring, support link | Destinations and handlers traced. No additional disconnected control identified. Sign out and workspace-changing actions were not executed on the live account. |
| Overview and trends | Overview, trends route, exposure links, severity disclosures, empty-state source | UI-06. Populated local records and empty-state wiring considered separately. |
| Product/component/release inventory | All three views, create links/forms, row/menu destinations, search/filter/pagination wiring | No additional disconnected control identified. Record creation/deletion was not performed on the live account. |
| Product details | All 13 local products, details accordions, component/release links and dialogs, visibility/action wiring | UI-01 and UI-03. |
| Release history and details | 13 product histories, 19 local release pages, add-artifact dialog, edit/download/action wiring | UI-07. Add-artifact dialog opened with available records. Adding/removing release artifacts was not submitted live. |
| BOM components | All 24 local BOM components; upload, metadata, CI/CD, trusted-publisher and sharing wiring | Upload and metadata dialogs opened in Chrome. UI-05 and UI-06. |
| Document components | All six local document components, inline uploader and row/editor wiring | UI-04 and UI-05. |
| Artifact history/details | 24 histories, 40 SBOM details, one CBOM detail, eight document details, download destinations | No additional disconnected control identified. No standalone VEX artifact was present in local seed data; its conditional controls were inspected in source. |
| Vulnerability scans/reports | Workspace scans, trends, 40 individual SBOM reports, assessment/report/triage wiring | No additional disconnected control identified. Scheduling a scan and saving triage were not executed live. |
| Cryptography | Workspace empty state, local CBOM detail, inventory/posture fragment and filter wiring | No populated workspace crypto assessment data in the local account. Populated roll-up interactions need fixture/integration coverage. |
| Security advisories | List, create form, all 17 local detail pages, draft/published state controls and product links | Forms/actions have handlers. Publishing, linking VEX and posting updates were not submitted live. |
| Plugins | Page, asynchronously loaded summary/settings, enable/configure/save wiring | Settings loaded. Saving configuration and running external assessments were not performed. |
| Settings: General | Workspace name/default, freshness, patch targets, danger-zone wiring | No additional disconnected control identified. Saves and deletion were not submitted live. |
| Settings: Members / Account | Member/invitation actions, role explanations, account fields and permission gates | Source and owner-page inspection; member sharing gap isolated separately as UI-05. Invitation email and membership changes were not submitted live. |
| Settings: API tokens | Token form/list and revoke/copy wiring | Destinations/handlers traced. Live credentials were not created, copied or revoked. |
| Settings: Parties | List/search, new and existing profile forms, entity editor, standalone fragment behaviour | Embedded form/editor opened correctly. UI-02 affects direct fragment navigation. |
| Settings: Trust Center / Branding | Access controls, domain/slug forms, security.txt, NDA guidance, description, logo/colour preview wiring | No additional disconnected control identified. Approval/revocation, uploads and public-setting saves were not submitted live. |
| Settings: Billing | Local billing-disabled behaviour plus priced-plan fixture, plan selection and checkout outcome pages | Stripe checkout/portal execution remains an integration check. |
| Workspaces / suppliers | Workspace dashboard and invite form; supplier page and mutation wiring | No additional disconnected control identified. Workspace switching/default/deletion and invitations not executed live. |
| Onboarding | Welcome/setup/complete/plan states rendered in fixtures, compatibility redirect, unsubscribe form/source | Actual delivery links and completion submissions are not covered by the read-only live sweep. |
| CRA | Product list, scope screening, all five wizard steps in isolated fixtures, navigation/document-action wiring | UI-02 and UI-03. Assessment generation/export requires a completed fixture and storage integration. |
| Public Trust Center | Workspace/advisory index, seven public products/histories, 12 public releases, 18 public components and available artifact/advisory variants | Access-denied/hidden-advisory responses were checked as permission states, not counted as dead links. |
| Access request / NDA | Request and signing pages rendered in isolated fixtures, admin queue/action wiring traced | No request emails, approvals or legally meaningful signatures were submitted. |
| Generated public VDP / declaration | Templates and gates traced; both pages rendered in isolated fixtures with mocked document content; back links clicked | No generated documents in the live seed data. Actual document generation/storage remains an integration check. |
| Contact / auth / error pages | Support and enterprise contact forms, success/cancel screens, login-error and missing-page responses; auth hand-off source | No email/support submissions or external identity-provider session changes. |
| Compliance catalog management | Source/caller/route inventory and legacy destination checked | UI-03: currently orphaned. |

## Items deliberately not classified as broken

- Branding-preview navigation uses `href="#"` because it is a preview. These were the only visible bare-hash anchors found in the corrected sweep.
- Template `href="#"` fallbacks on downloads/advisories/assessment controls are replaced by Alpine bindings. A source-only placeholder search would incorrectly flag them.
- **Generate Report / Coming soon** exists in the old `quick_actions.html.j2` component, but that component has no current page caller. It is dormant code, not a broken action on the current dashboard.
- Locked plan features, unavailable actions and access-denied screens are intentional states. Anonymous access to restricted artifacts/advisories must not be interpreted as a broken destination.
- Private-product public URLs found in the initial source/DOM inventory are hidden after Alpine applies visibility state. They were not treated as visible broken links.
- Seed-data links to example sites are sample content. Their external destinations were not classified as application wiring defects.
- Standalone fragments are not generally full pages. UI-02 is actionable because a real full-page link directs users to one.

## Remaining verification actions

These are coverage follow-ups, not confirmed defects:

- [x] Exercise Stripe checkout and the customer portal with billing enabled and sandbox credentials.
- [x] Verify invitation, support, enterprise-contact, access-request and unsubscribe email journeys with a test mail sink.
- [x] Exercise complete CRA generation/export and public VDP/declaration downloads against test object storage.
- [x] Add populated cryptography and standalone VEX browser scenarios, including filters and report links.
- [x] Run an external identity-provider sign-in/sign-out round trip and a custom-domain Trust Center navigation pass.
- [x] After fixing UI-01 to UI-07, run role-specific browser regressions and confirm successful save/upload/delete/triage flows in isolated fixtures.

The audit did not exhaustively submit every form, traverse every data/permission combination, or validate every external destination. Django admin, API documentation, TEA machine endpoints, provider-owned authentication screens and the DEBUG component gallery are outside the migrated customer-page audit. Their existence was distinguished from app pages during route inventory.

# Prototype UI migration

The first slice moves the private app frame and Overview onto the composition in
`/Users/lucgibson/Designs/sbomify-prototype`. The prototype is a visual and interaction
reference. Django remains the source of page data; the prototype's browser-local
model, HTML injection and stylesheets are not dependencies of the app.

| Prototype area | First production slice |
| --- | --- |
| Rail and top bar | A fixed 240px rail, neutral active state, Monitor / Ship / Prove groups, compact search, account menu and sticky footer. Mobile navigation uses a drawer. |
| Workspace picker | Existing workspace switching and creation, composed with the dropdown library. |
| Metrics | Open occurrences, occurrences past the workspace patch SLA, known exploited occurrences, and components with stale SBOMs. Zero values stay neutral. |
| Quick actions | Product, release, component and advisory creation. The release page selects a workspace product and preserves form input on validation errors. |
| What to fix first | The latest completed provider results for each component's latest SBOM, merged by advisory alias and filtered by VEX. Malicious packages and known exploitation lead, followed by a breached patch SLA, severity and the nearest deadline. Rows show the current VEX decision and product membership. |
| Exposure by product | The same workspace snapshot grouped through product membership, with severity bars and an explicit unassessed state. Shared components count once in workspace totals and appear under each product that contains them. Evidence distinguishes stale SBOMs, missing SBOMs and current uploads. |
| First visit | Metrics, actions and both panels remain visible with honest empty states. A compact callout opens the existing repository setup and upload dialogs. A workspace containing documents is not mistaken for an empty workspace. |
| Trends | Moved to a dedicated page, reached from the Overview view switch and Spotlight. The existing product, release and date filters remain intact, and the page URL carries them. |

Every visual recipe lives under `templates/components`. Chrome and overview
panels compose shared layout, button, badge, card, table and feedback components.
Stat cards, action tiles and panel headings use the same bases as other pages. The gallery demonstrates the new
components. Both dashboard base templates share one frame. Permission-sensitive
chrome is rendered from live capability flags without fragment caching.
The top bar composes separate search, creation, notification and account controls.
The compact account menu uses the shared avatar as its trigger, links directly
to account and API-token settings, and keeps theme, documentation, support and
sign out together. The neutral New button and quiet bell share existing button
bases. Notification rows and loading, empty and error states come from Cotton
components; the notification script only fills data and manages refreshes.
The search dropdown now uses inset rows, a neutral selection and quiet keyboard
hints. Its Cotton component owns presentation, with Alpine handling keyboard
and pointer selection, focus and cancellation of pending searches. Results scroll
inside the panel, which fits narrow and short screens. The live gallery includes
a second instance to demonstrate the shared component. Focusing an empty field
opens preloaded page suggestions and example searches immediately. Both come
from the existing destination registry and respect live workspace permissions.
Choosing an example fills the field and runs the search; clearing the query
restores suggestions without another request.
The onboarding component owns its setup and upload dialogs, so pages only place
the component and load the existing SBOM entry point when needed.

The overview service returns `ServiceResult` and batches product membership and
assessment reads. Patch deadlines join current findings to open lifecycle records
by component and advisory aliases, taking the earliest recorded sighting.
Best-effort policies and missing history stay explicit. The migration does not
change uploaded artifacts, assessment results, permissions, schema or the
application's colour tokens.

## Products inventory

Products now holds Products, Releases and Components as linked tabs, with counts,
search, risk and visibility filters, product filtering, server sorting and pagination.
The old component and release list URLs still open their corresponding tabs.
Ship and Spotlight use the unified destination. Existing creation, download and
detail routes keep their permission checks.

The page composes shared compact table cells, linked navigation tabs, native
filters, the existing pager and floating menus. Exposure bars share the overview
renderer; bars at both sizes open an accessible severity breakdown. Evidence and scan
states use one quiet status component. The gallery renders the new composition.
The three old Alpine table controllers and their separate templates were removed.

Inventory data comes from a service that checks live workspace membership before
reading rows. Overview and inventory share the component security snapshot,
including latest provider results, advisory aliases, VEX suppression and patch
SLAs. Releases aggregate their own pinned artifacts in batches, rather than taking
the latest component SBOM. Unassessed, skipped and summary-only results retain
their meaning. Missing SBOMs and missing freshness policies stay explicit.

Product and component models do not record modification times, so the prototype's
Modified at column is omitted. Created at shows the recorded creation time.
Product details and release history now reuse this composition, as described below.

## Following slices

- The prototype's vulnerability queue and internal Trust Center landing page need
  their own page migrations. Navigation currently names the real destinations:
  Vulnerability scans and the existing Trust Center settings.
- Posture currently opens the existing CRA page and retains its admin gate.

The refreshed homepage baselines cover four widths. The remaining page snapshot
baselines should be reviewed as their pages migrate; their shared chrome changes
with this slice.

## Product details and release history

Product details now composes the shared stat cards and inventory table, with a
visible SBOM download menu, component assignment and a release preview. Metrics
cover the product's current components; searching the table does not change the
metrics. Document components do not acquire a security assessment status. Each
release preview uses the assessment results for its own artifact collection.

The complete release history uses the same inventory filters, rows, sorting,
pagination and vulnerability dropdowns. Release creation uses one full-page form
from the navbar, dashboard, inventory and product pages. Product links preselect
the product. Editing remains a shared dialog. The editor reads server-supplied
records, writes through the existing release API and refreshes its owning frame
through HTMX. Empty versions can be cleared without clearing the release name.

Product membership uses server-backed forms. Each operation reads the current
membership before assigning or removing one component, preserving other links.
Workspace boundaries and live capabilities remain authoritative. The product's
links, identifiers, lifecycle and CRA assessment retain their existing workflows
inside the shared native accordion.

The component table has its own frame for filter replacements. The surrounding
header, metrics, release preview and expanded settings are not rebuilt when a
filter changes. A membership change refreshes the whole product frame and its
metrics. Both the page and nested frames use the default component gap.

The prototype's release selector and product-wide vulnerability queue remain
part of the release/artifact and vulnerability slices below. This page currently
labels its scope as current components and links to the real release collections.

Validation covers 574 component, service and navigation checks, plus 12 reviewed
product and release-history snapshots across four widths. The frontend build,
lint, template checks and targeted Python type checks pass.

## Plugins

Plugins now uses the shared stat cards, category card headers, selectable rows,
form fields and feedback components. The page frame owns section spacing and
each category is one card. Descriptions remain readable on touch screens.
Checkboxes reflect the explicit Save changes workflow, with actions above and
below the list. Configuration fields, plan restrictions and the summary refresh
continue through the existing HTMX endpoints.

Browser coverage checks saving and reloading every field type, keyboard selection,
the upgrade link and empty state. Responsive screenshots cover four widths.

## Remaining migration order

| Group | Remaining work |
| --- | --- |
| Release and component details | Release artifact table and collection metadata; BOM/document component pages, uploads, setup, memberships and artifact details. |
| Security | Vulnerability queue, artifact vulnerability detail, scan history, crypto assessments and trends. |
| Posture | Product CRA list, scope screening and assessment steps, retaining the production classification and evidence workflow. |
| Trust Center and advisories | Internal landing and management flows, advisory list/detail/editor, and customer-facing pages where they still differ from the prototype. |
| Supporting pages | Workspace selection/invitations, onboarding, billing and creation flows that remain outside the migrated settings and inventory surfaces. |

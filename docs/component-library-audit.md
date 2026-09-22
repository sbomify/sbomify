# Component library consolidation

On 14 September 2026, reviewed the 180 templates in `sbomify/templates/components`, their composition
relationships and their callers. Ten redundant templates were removed. That pass left 170 templates, including the smaller branded library.
Subsequent page migrations extend those primitives and add domain compositions.

## Consolidated patterns

| Pattern | Shared implementation | Migration |
| --- | --- | --- |
| Stat cards | `layout/stat_card.html` | Dashboard, scans, trends, assessments, crypto, billing and public release summaries use one value/label API and the same design. `compact` changes density. `x_value` binds a client value and its zero state. The old overview metric and three stat layout parts were removed. |
| Action tiles | `layout/action_tile.html` | Dashboard actions use `flush` inside their shared strip. Framed actions use the same content, icon, state and link/button handling. The overview action was removed. |
| Compact panel headings | `cards/header.html` | `compact`, `title` and `hint` cover overview panel headings. The separate overview heading was removed. |
| Severity badges | `badges/severity.html` | Server `level` and client `data-level` select the same recipes. The runtime-only severity component was removed. |
| Semantic badge shells | `badges/badge.html` | Dynamic badges now compose the same shell as static and action badges. Button and span forms also share one recipe. |
| Search fields | `forms/search_input.html` | Form and navigation searches use the default size; table toolbars use `size="sm"`. The separate table search was removed. |
| Select fields | `forms/select.html` | `size="sm"` is a small inline field, `size="md"` fits toolbars, and the default fills a form. The separate table select was removed. |
| Accordion sections | `navigation/accordion_item.html` | `native` uses details/summary; `state` keeps caller-owned Alpine state. Trigger and body recipes are shared. The separate disclosure was removed. |
| Pager controls | `navigation/page_link.html` | Server links, current-page spans and client buttons share size and state recipes. `page_button.html` remains a thin adapter. |

All callers and gallery examples were migrated. There are no remaining template
references to the removed components. Pages continue to supply data, layout and
event bindings; visual recipes remain inside components.

## Patterns retained after review

| Families | Why they remain separate |
| --- | --- |
| Button, badge and tag colour variants | These already nest their family base and pass `variant_class`. They are the repository's intended variant structure. |
| Branded components | Public workspace identity has separate colour and contrast rules. Its components remain in the branded library and use main-library controls where required. |
| Stat cards, metric chips and branded figures | Cards are standalone readouts, chips are inline metadata, and branded figures are an unboxed public strip. They differ in structure and placement. |
| Cards, inset panels, table frames and footer bands | These own different containment, padding and scrolling relationships. Existing card variants already share their base. |
| Alerts, toasts, callouts, loading and empty states | Persistent explanations, live announcements, form-bearing notices and waiting states have distinct semantics and content. |
| Form inputs, textarea, checkbox, radio, toggle and upload controls | Native element behaviour, validation and submitted state differ. Search and select duplication was consolidated within those control types. |
| Tabs, segmented controls, steppers and navigation links | Their keyboard behaviour and accessible relationships differ. A segment is not a tab, and a step is not a destination. |
| Accordion sections and collapsible cards | Accordion sections share a divided container; assessment cards own independent status, surface and body lifecycles. |
| Page headings, section introductions and card heading bands | They occupy different places in the heading outline and compose different supporting content. Duplicate overview card headings now use the card band. |
| Dialog wrappers and standalone controls | Dialog wrappers already compose `modal.html`. Date selection, secret reveal, copying, code display, avatars and progress have distinct interaction contracts. |
| Chrome and overview domain panels | Chrome composes shared controls. Overview panels supply product, evidence and vulnerability-specific content through those primitives. |

The component comments and `/design-system/` gallery remain the API and visual
references. The gallery demonstrates default and compact cards, reactive values,
action layouts, native and controlled accordions, and both pager modes.
Component render checks cover all families; browser checks cover the dashboard
and scans at desktop and mobile widths plus the gallery's shared interactions.

## Products inventory pass

- Table cells and headers accept `compact`; server sort links use the same header
  component as existing Alpine sort controls. `toolbar` accepts `flush` for filters
  outside the table frame.
- Tabs accept navigation links with `aria-current`, while button tabs keep their
  existing tab semantics and keyboard handling.
- Overview and inventory share exposure bars and evidence presentation. Both bar
  sizes open the existing floating dropdown surface with a severity breakdown.
- `feedback/status` owns the quiet dot-and-label treatment for evidence, freshness,
  scan and visibility states.
- Inventory filters, rows, row actions and the footer compose the library. Five
  superseded page/table templates and three inline table controllers were removed.
- The live gallery includes the composed inventory and its new component modifiers.
- Isolated Cotton renders reuse application context within one request. Nested
  components no longer repeat workspace, notification and version lookups. Every
  new request reads live membership; switching user or workspace also refreshes it.
- Inventory updates inherit `show:none`, so boosted tabs, sort links and pagination
  do not scroll the replacement content into view.

## Workspace settings migration

All eight sections compose the existing cards, tables, actions, fields and
feedback components. `forms.field` has one responsive horizontal layout;
`forms.input` and `forms.color_field` add compact sizes. File picking now shares
`forms.file_upload` and `forms.file_preview` with the rest of the app. The public
branding preview is a single semantic component built from the public library.
The design-system gallery demonstrates the modifiers, static table records,
scrolling tabs and standalone theme picker.

Settings tabs replace only their content, preserve scroll position and use real
URLs. General, branding, tokens and party profiles render on the first response.
Their refresh endpoints reuse the same context builders. Settings state is in
the central Alpine registry so initial HTML and later partials initialize alike.
Token pages disable HTTP and HTMX history caching; lists remain scoped to the
current user. Workspace permissions remain live, including admin access to Trust
Center dialogs and owner-only workspace deletion.

Patch targets save to the existing workspace policy and invalidate the dashboard
cache after commit. Their refresh leaves unsaved name/freshness edits intact.
Prototype-only notification preferences and workspace-leaving controls are not
presented as working settings. Account identity remains managed by the identity
provider; account deletion keeps the existing confirmation and grace period.

The shared HTMX lifecycle restores disabled state only on the original buttons,
leaves Alpine's inline visibility styles intact during settling, and handles
history restoration without assuming request-specific event details. The party
list uses that lifecycle instead of attaching another global swap listener.
Selected settings tabs stay visible at narrow widths without vertical scrolling.

`layout/frame.html` owns the default 1.5rem vertical gap on the app canvas,
Settings and Products replacement roots, and narrower form pages. Page and
section headers have no external margin; the page header has no `flush` option.
Nested sections use flex/grid gaps for their internal spacing. Hidden state
mounts and submission-only forms stay out of normal flow, so they cannot create
empty rows. The gallery demonstrates the same composition.

## Colour token audit

Shared components use the existing palette for foregrounds. Stat values, change
indicators, severity badges, assessment pills, format badges and metric chips no
longer blend their ink with body text or define local hues. Surfaces and borders
retain transparent token tints. The gallery now shows the existing severity,
information and neutral tokens alongside the original swatches.

Source checks reject local hues, undefined colour variables and mixed foregrounds
across the component library. Browser checks compare the rendered components with
the gallery swatches in both themes, including zero and reactive stat values.

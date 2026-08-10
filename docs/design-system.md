# sbomify Design System

The contract for **all** UI work in this codebase — for humans, Claude sessions, and any other coding agent. Read this before writing or changing any template, style, or component. The living gallery at `/design-system/` (URL name `core:design_system`, registered only when `DEBUG=True`) renders every component in one view; this document is the written contract behind it.

## The rules

1. **Never hand-roll UI the library already provides.** Before building anything, check the component inventory below and the gallery. If a button, card, form control, toast, table, or badge exists, use it.
2. **Tokens only.** Never hardcode hex/rgb colors, shadows, or radii in templates or CSS. Use the CSS custom properties (`var(--color-*)`, `var(--shadow-*)`). A raw hex in a diff is a review blocker.
3. **Extend by parameterization, not duplication.** Component families are parameterized with custom properties (`--btn-accent`, `--toast-accent`, `--alert-accent`, `--stat-accent`, `--progress-accent`). A new variant sets those properties on a modifier class — it does not copy the base rules.
4. **Both themes, always.** `:root` defines the dark theme; `:root.light` overrides for light. Anything built from tokens adapts automatically; if you find yourself special-casing a theme, you are probably not using tokens.
5. **Every library change lands in the gallery.** New component or variant → add a demo to `sbomify/apps/core/templates/core/design_system.html.j2` and a row to the inventory here, in the same PR.

## Design language

- **Calm surfaces.** Cards and containers are `--color-surface` with a 1px `--color-border` hairline, `0.75rem` radius, and the resting `--shadow-card`. Containers do not move: no hover lift, no hover shadow swap, no animated accent bars. The only entrance motion is the card family's `fadeInUp`.
- **Filled controls carry a soft gradient.** Filled buttons use `linear-gradient(135deg, accent 0%, accent-dark 100%)` with a 0.5px self-colored border and an inset top highlight. Hover lightens the gradient — nothing translates. Active is `scale(0.98)` with an inset shadow.
- **Accent lives in chips.** Icon accents use a flat tinted chip: `color-mix(in oklab, accent 12%, transparent)` background with the accent as foreground (see toasts, stat cards, modal header icons). No gradient chips, no colored side-borders.
- **Text on tinted backgrounds mixes toward the theme text color.** Never place a raw accent color as text on its own tint; use `color-mix(in oklab, accent 60–70%, var(--color-text))` so contrast holds in both themes (see alerts, stat deltas).
- **Data is tabular.** Numbers that update or align in columns (stats, deltas, progress values) get `font-variant-numeric: tabular-nums`.
- **Type** is Figtree throughout. Labels over data use the small-caps pattern: `0.75rem`, weight 600, uppercase, `letter-spacing 0.06em`, `--color-text-muted`.
- **Motion is earned.** Width/opacity transitions and deliberate one-shot entrances are fine; infinite/ambient animation is reserved for true loading states (skeleton shimmer, brand loader). Respect `prefers-reduced-motion` (the stylesheet already gates it).

## Tokens

All tokens live in `sbomify/assets/css/tailwind.src.css` — `:root` (dark, the default) and `:root.light`. Core sets:

| Group | Tokens |
| --- | --- |
| Brand/interactive | `--color-primary`, `-dark`, `-light`, `-lighter` |
| Semantic | `--color-success`, `--color-warning`, `--color-danger` (each with `-dark`, `-light`) |
| Accents | `--color-accent`, `--color-accent-pink`, `--color-accent-orange` |
| Surfaces | `--color-background`, `--color-surface`, `--color-surface-elevated` |
| Lines & text | `--color-border`, `--color-border-light`, `--color-text`, `--color-text-muted` |
| Shadows | `--shadow-xs`, `--shadow-card`, `--shadow-card-hover`, `--shadow-inner` |
| Raised edges | `--edge-highlight`, `--edge-underline` — the top/bottom inset edges that make a surface-coloured control read as raised. Each theme states its own: on dark the surface is navy and takes a light top edge; on light it is pure white, where a white highlight is invisible, so the raise comes from the bottom edge. |

Derive intermediate shades with `color-mix(in oklab, …)` from these — do not invent new hex values.

## Using components

Two layers, used together.

**Component tags** — the way pages call the library. `{% load design_system %}`, then containers are block tags and leaves are inline tags, so a card genuinely *contains* library components:

```jinja
{% load design_system %}
{% card variant="dashboard" title="Releases" %}
    {% badge text="3 overdue" variant="danger" %}
    {% input name="q" label="Search" hint="Name or identifier" %}
    {% button text="New release" variant="primary" hx_get=new_release_url hx_target="#list" %}
{% endcard %}
```

Each tag renders the matching template in `sbomify/apps/core/templates/components/tw/`, so the macro file remains the single source of a component's markup **and** its parameter contract; the tag only provides the calling convention. `{% include "components/tw/…" %}` still works and is equivalent for leaves — but a container must use the block tag, because an include cannot wrap content.

Attribute passthrough: a keyword argument prefixed `aria_`, `data_`, `hx_` or `x_` becomes the dashed HTML attribute (`hx_post` → `hx-post`), with its value escaped; `True` renders the bare attribute; `None`/`False` are omitted. Attribute names Python cannot express — Alpine's `@click`, `:class` — go through `attrs` as a raw trusted string, never user input.

Registered tag names are the file names in `components/tw/`, with one alias: `{% breadcrumbs %}` renders `breadcrumb.html.j2` (the name `breadcrumb` is taken by a trust-center-only inclusion tag).

List-taking components (`select`, `tabs`, `breadcrumbs`, `pagination`, `dropdown`) receive their lists from the view context — build them in the service layer/view, not inline.

| Component | Use for | Key params |
| --- | --- | --- |
| `alert` | Inline notice banners | `variant`, `title`, `message`, `dismissible` |
| `analytics_consent` | PostHog consent banner (base templates only) | — |
| `avatar` | User initials/status | `initials`/`src`, `size` (defaults `md` — the base class has no size of its own), `status` |
| `badge` | Status labels | `text`, `variant`, `icon`, `pill` |
| `breadcrumbs` | Page trail | `items` (list of `{label, url}`) |
| `button` / `button_link` | Actions / link styled as button | `text`, `variant`, `size`, `icon`, `loading` / `url` |
| `card` | Content containers | `variant` (`dashboard`/`danger`/default), `title`, `subtitle`, `content`, `footer_content` |
| `checkbox` / `radio` / `toggle` | Form controls | `name`, `label`, `checked`, `disabled` |
| `code_block` | Copyable code | `code`, `language`, `filename`, `max_height` |
| `confirm_modal` | App-wide confirm dialog (already in base) | dispatch `confirm:show` event |
| `dropdown` | Action menus | `id`, `trigger_text`/`trigger_icon`, `items` (supports `divider`, `danger`, `disabled`) |
| `empty_state` | No-content placeholder | `icon`, `title`, `message`, `action_text`, `action_url` |
| `icon_button` | Icon-only actions | `icon`, `label` (aria), `variant` |
| `input` / `textarea` / `select` | Form fields | `name`, `label`, `hint`, `error`, `required` |
| `loading_state` | Placeholder for an in-flight HTMX panel | `message`, `size`, `compact` |
| `modal` | Alpine-driven dialog | `id`, `title`, `content`, `size`, `alpine_show` |
| `pagination` | Page navigation | `current`, `total`, `page_range`, `base_url` |
| `progress` | Determinate progress | `value`, `variant` (omit for the primary accent), `size`, `label_text` (renders the header row) |
| `skeleton` / `spinner` | Loading states (prefer the brand loader for spinners) | `type` (`text`/`paragraph`/`avatar`/`button`/`image`), `width`, `lines` / `size` |
| `table_pager` | Compact Alpine table pager | expects `currentPage`, `totalPages` in scope |
| `tabs` | Tab lists | `tabs` (list of `{id, label, icon}`), `active`, `variant` |
| `tag` | Removable/tech tags | `text`, `icon`, `variant` (omit for neutral), `removable` |
| `toast` / `toast_container` | Notifications (container already in base) | dispatch `toast` event `{type, title, message}` |
| `token_display` | Masked secrets with copy | `label`, `token`, `masked`, `copyable` |

Brand marks (logo, emblem, animated loader) are separate includes under `core/components/brand/` — always use `loader.html.j2` instead of ad-hoc spinners.

**CSS class families** in `sbomify/assets/css/tailwind.src.css`, one commented section per family (search `Component Classes -`). Highlights:

| Family | Classes |
| --- | --- |
| Buttons | `tw-btn-{primary,secondary,ghost,gradient,success,warning,danger}`, `tw-btn-outline-{primary,warning,danger}`, sizes `tw-btn-{sm,lg}`, `tw-btn-loading` |
| Cards | `tw-card`, `tw-dashboard-card`, `tw-dangerzone-card` + `tw-card-{header,body,footer}`, `tw-collapsible-card` + `tw-collapsible-*` (the settings card was removed — use `tw-dashboard-card`) |
| Forms | `tw-form-{label,input,select,textarea,error,hint}`, `tw-checkbox`, `tw-radio`, `tw-toggle` (+ `tw-toggle-label`), `tw-search-input-*`, `tw-file-upload-*`, `tw-date-picker-*`/`tw-calendar-*` |
| Data | `tw-table` (the `<table>`) inside `tw-data-table` (the shell: `-toolbar`, `-container`, `-footer`, `-search`, `-info`, `-page-size`), `tw-stat-*` (+ `tw-stat-card-compact`), `tw-progress-*` (+ `tw-progress-header`) |
| Feedback | `tw-alert-*`, `tw-toast-*`, `tw-badge-*` (+ `tw-badge-severity-{critical,high,medium,low}`), `tw-sbom-format-*`, `tw-tag-*`, `tw-empty-state-*`, `tw-skeleton-*`, `tw-brand-loader`/`tw-loader-*` |
| Navigation | `tw-tabs`/`tw-tab`, `tw-pagination-*`, `tw-breadcrumb-*`, `tw-dropdown-*`, `tw-icon-btn` (+ `-sm`, `-danger`), `tw-stepper-*` |
| Accent | `tw-icon-chip` (+ sizes `-sm`/`-lg`/`-xl`, `-circle`, and `-neutral`/`-info`/`-success`/`-warning`/`-danger`) — the flat tinted chip behind every icon-beside-a-heading |
| Layout | `tw-page-header` (+ `-lead` for a mark beside the title, `-title`, `-subtitle`, `-actions`, `-flush` inside a `space-y-*` stack), `tw-section-header` (+ `-title`, `-subtitle`) with `tw-section-body` to indent under the title, `tw-metric-chip` (+ `-label`, `-value`) for the stats strip |
| Selection | `tw-select-row` — a list row that is clickable in full. Selected state comes from `:has(:checked)`, never a class, so it cannot drift from the control; keep a real checkbox for keyboard and form submission and add the row click as a pointer convenience, guarded so nested controls still work. |
| Type | `tw-data-label` (small-caps label over a value), `tw-code-inline` (identifier in prose) |
| Misc | modal, `alpine-tooltip` (via the `x-tooltip` directive), copy button / token display / code block |

Two names that are easy to get wrong:

- **`tw-table` vs `tw-data-table`** — `tw-table` styles the `<table>` element; `tw-data-table` is the surrounding shell. A `<table class="tw-data-table">` gets no cell padding.
- **`tw-stat-row`** is the wrapper *inside* a stat card that sits the delta on the value's baseline. Laying out a row of stat cards is the page's job (a grid utility).

Removed in the v2 consolidation — do not reintroduce without three real callers: timeline, list group, range slider, `tw-tooltip` (CSS-hover; use `x-tooltip`), dividers, notification badge, `tw-table-striped`, `tw-tag-outline*`, `tw-avatar-group`, `tw-modal-{backdrop,container}`.

## Recipes

**The three-caller rule.** A pattern earns a place in the library at three or more *distinct* callers. Below that it stays page-local markup composed from library primitives. Rejected under this rule during the v2 consolidation, and recorded so it is not re-proposed without new evidence: a selectable tile (3 files, three divergent geometries — page-local until the geometries converge).

Count callers with a *loose* pattern before rejecting one. The metric chip was rejected first time round on a regex that required `text-xs`; the real shape uses `text-sm`, and it turned out to have 17 instances across 6 files. It is now `tw-metric-chip`.

**New variant of a parameterized family** — set the accent properties on a modifier class; never restate the base rules:

```css
.tw-btn-violet {
  --btn-accent: var(--color-accent);
  --btn-accent-dark: color-mix(in oklab, var(--color-accent) 80%, black);
  --btn-accent-hover: color-mix(in oklab, var(--color-accent) 72%, white);
}
```

**Readable text on a tint:** `color: color-mix(in oklab, var(--color-warning) 60%, var(--color-text));`

**Accent icon chip:** `background-color: color-mix(in oklab, var(--accent) 12%, transparent); color: var(--accent);`

## Creating a new component

**The decision rule.** When you need UI that doesn't exist yet:

1. **It exists** → use it (inventory above / gallery).
2. **It's a variant of an existing family** (new color, size, emphasis) → add a modifier class that sets the family's custom properties. Never fork the base rules.
3. **It's genuinely new** → build it **in the library**, then consume it from your feature — never define it inside an app template or app-level CSS. Pages may *compose* library components with layout utilities (grid/flex/spacing); the moment you write component-like markup — a styled control, a repeated visual pattern, anything that wants its own class — it belongs to the library, even if today it has one caller.
4. **You find an existing in-app one-off** that should be shared → promote it: move it into the library, replace the original usage, don't copy it.

**Conventions for new components:**

- **CSS naming**: block `tw-<component>`, parts `tw-<component>-<part>`, modifiers `tw-<component>-<variant|size>` (e.g. `tw-stat-card`, `tw-stat-label`, `tw-stat-accent-danger`). Accent parameterization uses `--<component>-accent`. CSS lives in `tailwind.src.css` under the matching `Component Classes - <Name>` banner, or a new banner section for a new family.
- **Macro API**: file `components/tw/<component>.html.j2`, snake_case, Django template syntax. Reuse the standard param names — `name`, `label`, `variant`, `size`, `checked`/`disabled`, `class` (extra classes), `attrs` (raw attribute passthrough, rendered `{{ attrs|safe }}`). List-shaped params come from the view context.
- **Style real elements.** State styling hangs off the actual interactive element (`input.tw-toggle:checked`, `:disabled`, `:focus-visible`) — not decorative siblings that can't carry state. (The toggle shipped broken for exactly this reason.)
- **Accessibility floor**: correct roles/aria (`role="progressbar"`, `aria-label` on icon-only controls), visible `:focus-visible` ring from the primary token, ≥44px touch targets for primary controls (36px acceptable for compact variants), `prefers-reduced-motion` respected for any animation.
- **Design-language conformance**: derive every visual decision from the language section above. If the new component needs a pattern the language doesn't cover, extend the language section in the same PR — don't invent silently.

**Ship checklist** (all in one PR):

1. CSS in `tailwind.src.css` per the conventions above, built from tokens, parameterized if it has variants.
2. A Jinja include in `components/tw/` if it has reusable markup.
3. A demo in the gallery (`core/design_system.html.j2`) plus an inventory row in this document.
4. Verify in the gallery in **both themes**; run `bun run build`, `uv run djlint … --lint`, and the design-system view tests.

## Anti-patterns (review blockers)

- Hand-rolled buttons/cards/form controls where a component exists
- Raw hex/rgb values, or Bootstrap classes (`btn`, `card`, `row`) in new work
- Hover lift/motion on containers; ambient infinite animation outside loading states
- Raw accent color as text on its own tint (fails contrast)
- New components or variants defined inside an app template or app CSS instead of the library
- New UI merged without a gallery demo
- **Wrapping a colour token in `rgb()`** — the tokens are already `rgb(…)`, so `rgb(var(--color-primary))` is invalid and the whole declaration is silently dropped. Use the token directly, or `color-mix(in oklab, var(--color-primary) 12%, transparent)` for a tint.
- Referencing a class that does not exist. It fails silently, so it survives review: grep the class in `tailwind.src.css` before shipping it, and remember class names also come from `.ts` files.
- Styling state on a decorative sibling instead of the element that carries it — a link can never match `:disabled`, so use `[aria-disabled="true"]`.
- **A Tailwind utility fighting a component class for the same property.** The `tw-*` classes are unlayered and emitted after Tailwind's utilities, so at equal specificity the component wins: `class="tw-stat-value text-danger"` renders in the default text colour, silently. When a component owns a property, recolour it through the component's accent custom property (`tw-stat-accent-danger`), never with a utility.

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

Derive intermediate shades with `color-mix(in oklab, …)` from these — do not invent new hex values.

## Using components

Two layers, used together:

**Jinja include components** in `sbomify/apps/core/templates/components/tw/` (Django template syntax despite the `.j2` extension). The macro file is the parameter contract; the gallery shows canonical usage. Include pattern:

```jinja
{% include "components/tw/button.html.j2" with text="Save changes" variant="primary" %}
{% include "components/tw/card.html.j2" with variant="dashboard" title="Releases" content="<p>…</p>" %}
{% include "components/tw/select.html.j2" with name="type" label="Artifact type" options=options selected=current %}
```

List-taking components (`select`, `tabs`, `breadcrumb`, `pagination`, `dropdown`) receive their lists from the view context — build them in the service layer/view, not inline.

| Component | Use for | Key params |
| --- | --- | --- |
| `alert` | Inline notice banners | `variant`, `title`, `message`, `dismissible` |
| `analytics_consent` | PostHog consent banner (base templates only) | — |
| `avatar` | User initials/status | `initials`, `size`, `status` |
| `badge` | Status labels | `text`, `variant`, `icon`, `pill` |
| `breadcrumb` | Page trail | `items` (list of `{label, url}`) |
| `button` / `button_link` | Actions / link styled as button | `text`, `variant`, `size`, `icon`, `loading` / `url` |
| `card` | Content containers | `variant` (`dashboard`/`danger`/default), `title`, `subtitle`, `content`, `footer_content` |
| `checkbox` / `radio` / `toggle` | Form controls | `name`, `label`, `checked`, `disabled` |
| `code_block` | Copyable code | `code`, `language`, `filename`, `max_height` |
| `confirm_modal` | App-wide confirm dialog (already in base) | dispatch `confirm:show` event |
| `dropdown` | Action menus | `id`, `trigger_text`/`trigger_icon`, `items` (supports `divider`, `danger`, `disabled`) |
| `empty_state` | No-content placeholder | `icon`, `title`, `message`, `action_text`, `action_url` |
| `icon_button` | Icon-only actions | `icon`, `label` (aria), `variant` |
| `input` / `textarea` / `select` | Form fields | `name`, `label`, `hint`, `error`, `required` |
| `modal` | Alpine-driven dialog | `id`, `title`, `content`, `size`, `alpine_show` |
| `pagination` | Page navigation | `current`, `total`, `page_range`, `base_url` |
| `progress` | Determinate progress | `value`, `variant`, `size`, `label_text` |
| `skeleton` / `spinner` | Loading states (prefer the brand loader for spinners) | `type`, `width`, `lines` / `size` |
| `table_pager` | Compact Alpine table pager | expects `currentPage`, `totalPages` in scope |
| `tabs` | Tab lists | `tabs` (list of `{id, label, icon}`), `active`, `variant` |
| `tag` | Removable/tech tags | `text`, `icon`, `variant`, `removable` |
| `toast` / `toast_container` | Notifications (container already in base) | dispatch `toast` event `{type, title, message}` |
| `token_display` | Masked secrets with copy | `label`, `token`, `masked`, `copyable` |

Brand marks (logo, emblem, animated loader) are separate includes under `core/components/brand/` — always use `loader.html.j2` instead of ad-hoc spinners.

**CSS class families** in `sbomify/assets/css/tailwind.src.css`, one commented section per family (search `Component Classes -`). Highlights:

| Family | Classes |
| --- | --- |
| Buttons | `tw-btn-{primary,secondary,ghost,gradient,success,warning,danger}`, `tw-btn-outline-*`, sizes `tw-btn-{sm,lg}`, `tw-btn-loading` |
| Cards | `tw-card`, `tw-dashboard-card`, `tw-dangerzone-card` + `tw-card-{header,body,footer}` (the settings card was removed — use `tw-dashboard-card`) |
| Forms | `tw-form-{label,input,select,error,hint}`, `tw-checkbox`, `tw-radio`, `tw-toggle` (+ `tw-toggle-label`) |
| Data | `tw-data-table`, `tw-stat-*` (+ `tw-stat-row`, `tw-stat-accent-*`), `tw-progress-*` (+ `tw-progress-header`) |
| Feedback | `tw-alert-*`, `tw-toast-*`, `tw-badge-*`, `tw-tag-*`, skeleton/`tw-skeleton-*` |
| Navigation | `tw-tabs`/`tw-tab`, `tw-pagination-*`, `tw-breadcrumb`, `tw-dropdown` patterns, `tw-icon-btn` |
| Misc | modal, tooltip, timeline, stepper, accordion, list group, file upload, search input, notification badge, dividers, date/time picker |

## Recipes

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

## Extending the library

Checklist for a new component or variant (all in one PR):

1. CSS in the matching `Component Classes -` section of `tailwind.src.css`, built from tokens, parameterized if it has variants.
2. A Jinja include in `components/tw/` if it has reusable markup.
3. A demo in the gallery (`core/design_system.html.j2`) plus an inventory row here.
4. Verify in the gallery in **both themes**; run `bun run build`, `uv run djlint … --lint`, and the design-system view tests.

## Anti-patterns (review blockers)

- Hand-rolled buttons/cards/form controls where a component exists
- Raw hex/rgb values, or Bootstrap classes (`btn`, `card`, `row`) in new work
- Hover lift/motion on containers; ambient infinite animation outside loading states
- Raw accent color as text on its own tint (fails contrast)
- One-off component variants defined inside an app template instead of the library
- New UI merged without a gallery demo

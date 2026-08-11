# Design system audit

## Status: conversion complete (2026-08-11)

The findings below are settled. A discovery pass over all 146 in-scope template
files verified 637 instances; 522 converted to the library, and the rest are
recorded leaves with reasons (rejected families stay page-local, one-off boxes
stay boxes, the oidc modal keeps its inline revoke button because a teleported
menu would open under the modal overlay).

The library grew by exactly the surface the callers needed: tw-btn-outline,
tw-badge-severity-unknown, tw-badge-solid-danger, tw-metric-chip accents,
tw-code-inline-primary, tw-inset-card, tw-dropdown-flush, tw-accordion-sm, the
tw-callout family, an --avatar-accent parameterisation, and four page_header
params (mark, editable title, copy_values, breadcrumbs). Each has a gallery
demo and an inventory row.

One root bug found on the way: public_base set --color-surface,
--color-surface-elevated and --color-border as bare triplets in inline styles,
and --color-primary the same way in its brand block, which silently dropped
every tailwind shorthand consuming them on public pages. Fixed by emitting
whole rgb() values; trust-center.css's nine compensating rgb(var()) wraps were
unwrapped in the same change.

The sweep now reports 6 conflicts, every one a named detector limit (padding
beside tw-card, which sets none; the badge pill parameter; a background beside
tw-data-label, which sets none), and zero undefined class names. All 46 moved
e2e baselines were reviewed image by image before regeneration; every move is
the intended conversion.

The original snapshot follows for history.

A snapshot of where the app still does not use the component library, taken
across 243 templates (trust centre and emails excluded, as they are out of scope
for this pass).

Read it with the counts as **upper bounds**. The detection is shape-based, so a
small inline panel counts as a "hand-rolled card" and a `w-5 h-5` box counts as
an input. The two conflict categories are precise; the hand-rolled ones need a
glance each.

## Why a class-name search misses these

Every bug found by review on this branch had the same shape: the element already
carried a library class, so grepping for `tw-btn`, `tw-card` or `tw-copy-btn`
found it and it looked converted. What was wrong sat next to the class.

- The advisories table used the library **toolbar** inside a hand-rolled card;
  products used a hand-rolled toolbar inside the library **card**. Both matched a
  search for `tw-data-table-toolbar` or `tw-card`.
- The Trust Center copy button used `tw-btn-secondary` and `tw-btn-success`
  together. Both are library classes. `tw-btn-secondary` is declared later, so it
  won the colour and the confirmed state never turned white.
- `tw-stat-value` with `text-danger` rendered in the default colour, because the
  component classes are unlayered and emitted after Tailwind's utilities.

So the search that finds them is not "which library classes are used" but
**"which library class has a utility beside it that sets the same property"**, and
**"which element has the shape of a component but none of its classes"**. That is
what this sweep runs.

## Findings

| Count | Files | What |
| --- | --- | --- |
| 239 | 86 | Hand-rolled card or panel: `rounded-*` with `border-border` and no `tw-card`/`tw-data-table` |
| 95 | 39 | Hand-rolled badge or chip: a `rounded` `bg-*` span at `text-xs` with no `tw-badge`/`tw-tag`/`tw-metric-chip` |
| 73 | 30 | An `<input>` with no form component class. Includes `w-4 h-4` checkboxes that should be `tw-checkbox` |
| 69 | 34 | Hand-rolled button: `<button>` with `rounded-*` and its own padding, no `tw-btn`/`tw-icon-btn` |
| 38 | 28 | **Padding or radius utility on a component that owns it** |
| 33 | 16 | **Colour utility on a component that owns colour** |
| 19 | 3 | Hardcoded colour in a `style` or `class` attribute |
| 0 | — | `tw-*` classes referenced but undefined. Nothing is silently missing |

The undefined-class check found only interpolated prefixes (`tw-badge-severity-`
from `class="tw-badge-severity-{{ severity }}"`), which a static check cannot
resolve. No dead class names.

### Status: fixed

The 113 conflict findings are down to 5, and those 5 are limits of the detector
rather than defects: `tw-card` does not set padding and `tw-data-label` does not
set a background, so a utility doing either beside them is not a conflict, and
`badge.html.j2` sets `rounded-full` conditionally because that is the component's
own `pill` parameter.

What the utilities turned out to be standing in for, now in the library:
`tw-badge-sm`, `tw-icon-btn-success`, `tw-btn-ghost-danger`, `tw-form-select-sm`
and `tw-form-select-{success,warning,danger}`. The rest resolved to variants that
already existed (`tw-btn-sm`, `tw-btn-lg`, `tw-icon-btn-danger`,
`tw-icon-btn-primary`, `tw-badge-danger`, `tw-btn-outline-danger`) or to a
declaration that was doing nothing and is gone.

### The two that failed silently, worst first (now fixed)

These are the ones to fix first: they look correct in the template, they pass
review, and the declaration simply never applies.

- `documents/access_request_queue_content.html.j2:76` — 7 × `text-text-muted` on
  `tw-icon-btn`
- `teams/dashboard.html.j2:54` — 5 × `text-[11px]` on `tw-badge-success`
- `compliance/cra_step_2.html.j2:170` — `text-[10px]` and `px-1.5 py-0.5` on
  `tw-badge-warning`
- `teams/team_tokens.html.j2:168` — 3 × `text-danger` on `tw-btn-ghost`
- `sboms/sboms_table_content.html.j2:263`, `sboms/components/crypto_inventory_card.html.j2:248`,
  `compliance/components/document_card.html.j2:21` — `px-3 py-1` on `tw-btn-*`

Each is either a variant that should exist in the library (a smaller button, a
smaller badge) or an accent that should go through the component's custom
property. Both routes are already documented; neither is a utility.

### The largest cluster

`contact_profiles/` (entity.html.j2, contact.html.j2, alpine_components.html.j2)
holds its own `entity-card` class, its own `w-full px-3 py-1.5` inputs and its own
checkboxes. It is the one area of the app that never went through the conversion
at all, and it is worth doing as a single piece rather than line by line.

## Suggested order

1. The 71 conflict findings. Small, precise, and each one is a style that is
   currently doing nothing.
2. The 73 inputs, since form controls are the part of the library that must be
   identical everywhere.
3. `contact_profiles/` as one job.
4. Buttons and badges, which are mechanical once the missing variants exist.
5. The remaining panels, deciding case by case whether each is a card or just a
   bordered box.

## Also outstanding, from earlier passes

- Hand-rolled table toolbars in five secondary tables: component detail, release
  artifacts, vulnerabilities, CBOM issues, component item.
- The three detail pages (product, component, release) still build their own page
  header instead of `page_header`.
- A visible "Actions" column heading on roughly 13 tables, where the products
  list and the product detail table now use `tw-table-actions` with an sr-only
  label.
- 287 em dashes across 90 templates. Most are inside `{% comment %}` blocks where
  the copy rule does not apply; the visible ones have not been swept.
- App-level CSS outside `tailwind.src.css` still contains `rgb(var(--token))`
  wrapping. The 13 in the main stylesheet are fixed.

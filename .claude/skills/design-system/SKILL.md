---
name: design-system
description: MUST be used for any user-facing UI work in this repo — creating or editing pages, Jinja templates (.html.j2), styles in tailwind.src.css, tw-* classes, component macros, buttons, cards, forms, modals, toasts, tables, colors, dark mode. Loads the sbomify design-system contract so UI is built from the shared component library instead of hand-rolled markup or hardcoded styles.
---

# sbomify design system

This repo has a shared component library and design language. UI work consumes it — it is not optional.

## Before writing any UI

1. Read `docs/design-system.md` (the contract: rules, tokens, component inventory, recipes).
2. Find the component you need in the inventory or the living gallery at `/design-system/` (DEBUG-only). The macro files in `sbomify/apps/core/templates/components/tw/` are the parameter contracts.

## The decision tree for any UI need

1. **Exists** → use it as-is.
2. **Variant of an existing family** → add a modifier class setting the family's custom properties (`--btn-accent` etc.). Never fork base rules.
3. **Genuinely new** → create it IN THE LIBRARY (CSS in `tailwind.src.css` under a `Component Classes -` banner with `tw-<component>-*` naming, macro in `components/tw/` with the standard param names), then consume it from your feature. Never define a component inside an app template or app CSS — even for a single caller. Follow "Creating a new component" in `docs/design-system.md`.
4. **Found a shareable one-off in an app** → promote it into the library and replace the original.

## Non-negotiables

- Use existing components (Jinja includes or `tw-*` class families). Never hand-roll a button, card, form control, badge, toast, or table.
- State styling goes on real interactive elements (`:checked`, `:disabled`, `:focus-visible` on the input itself), never on decorative siblings.
- Colors, shadows, and radii come from the CSS custom-property tokens in `sbomify/assets/css/tailwind.src.css` (`:root` = dark, `:root.light` = light). Never hardcode hex/rgb values.
- New variants parameterize (`--btn-accent`, `--toast-accent`, `--alert-accent`, `--stat-accent`, `--progress-accent`) — they never duplicate base rules.
- Containers sit still: no hover lift or ambient animation. Text on tinted backgrounds mixes toward `--color-text` (see the contrast recipe in the doc).
- Anything added to the library ships with a gallery demo in `core/design_system.html.j2` and an inventory row in `docs/design-system.md`, in the same change.

## After changing UI

Run `bun run build`, `uv run djlint <templates> --lint`, and check the gallery in both themes when the library itself changed.

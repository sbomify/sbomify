---
name: design-system
description: MUST be used for any user-facing UI work in this repo - creating or editing pages, Jinja templates (.html.j2), components in sbomify/templates/components/, tokens in tailwind.src.css, buttons, cards, forms, modals, tables, badges, colors, dark mode. Points at the live component library so UI is composed from it rather than hand-rolled.
---

# sbomify UI

The rules live in one place: the **Frontend (UI)** section of `AGENTS.md`,
which is already in context. Read it, then use the two live references below.
There is no separate design-system document.

## Before writing any UI

1. **Browse `/design-system/`** (DEBUG-only, URL name `core:design_system`).
   Every component, rendered, with its variants. Find the one you need.
2. **Read that component's file** in `sbomify/templates/components/`. Its
   opening comment is the parameter contract and explains why it is built the
   way it is. `buttons/` is the precedent to copy when building a new set.

## The decision

- **It exists** → use it.
- **It is a variant** (new colour, emphasis) → new file nesting the base,
  passing `variant_class`. Never restate the base markup.
- **It is a modifier** (size, state, density) → a prop, not a file.
- **It is genuinely new** → build it in `sbomify/templates/components/`, then
  consume it. Never define component-like markup in an app template, even for
  one caller.

Anything added ships with a demo in `core/design_system.html.j2` in the same
change.

## After changing UI

`bun run build`, then `uv run djlint <templates> --extension=j2 --lint`, and
look at the page in the browser in both themes. If it has an e2e snapshot,
expect the baseline to move only when you meant it to.

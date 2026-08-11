# Component library

The contract for `sbomify/templates/components/`, the cotton component layer.
The buttons set is the precedent: read `sbomify/templates/components/buttons/`
alongside this document before building anything. `docs/design-system.md`
remains the design language (tokens, spacing, motion, copy rules); this
document is how that language ships as components.

## The model

- A component is one `.html` file whose markup styles itself with **standard
  Tailwind utilities**. No `tw-*` component classes in new components, no
  additions to `tailwind.src.css`. The component file is the single source of
  its appearance.
- Components render as HTML-like tags anywhere, with no load tag:
  `<c-buttons.primary size="sm" hx-get="/x">Save</c-buttons.primary>`.
  Directory nesting maps to the tag name. File names are snake_case
  (`outline_primary.html`); tags may use hyphens (`<c-buttons.outline-primary>`).
- Sets live in subdirectories (`buttons/`, `badges/`, `cards/`, ...);
  components without real variants sit at the top level (`modal.html`,
  `avatar.html`).
- Isolation is on: a component sees only its declared props, `attrs`, and its
  slots. Django `{% include %}` still works inside a component for shared
  chrome (the brand loader).

## The rules

1. **Variants are files; modifiers are props.** `badges/danger.html` is a
   file; size, pill, density, disabled are props. A semantic set whose
   variants would multiply (a severity scale) may take a `level` prop instead;
   say so in the component's comment.
2. **One shell, never copied.** Variant files nest their base component and
   pass the recipe through `variant_class`; they forward everything else with
   `:attrs="attrs"` and explicit props. Never restate the base markup.
3. **The conditional-segment law.** Utilities that depend on a prop (size,
   variant, state) render as ONE `{% if %}` segment producing a complete,
   non-overlapping set. Two utilities for the same CSS property must never
   both land on an element: Tailwind resolves that by stylesheet order, not
   class order, and it will betray you.
4. **Colour through the theme.** Token-mapped utilities first (`bg-primary`,
   `text-text-muted`, `border-border`, `bg-surface-elevated`); arbitrary
   values referencing tokens for gradients and tints:
   `bg-[linear-gradient(135deg,var(--color-primary)_0%,var(--color-primary-dark)_100%)]`,
   `hover:bg-[color-mix(in_oklab,var(--color-border)_30%,transparent)]`.
   Spaces become underscores inside arbitrary values. Raw values only where
   the old CSS itself was raw, written as literals (`text-[rgb(15_23_42)]`).
5. **Slots over params for content.** Text, icons, and nested components go in
   the slot. Named slots (`<c-slot name="footer">...</c-slot>`) for secondary
   regions like a card footer. Lists (options, tabs, crumbs) are props built
   in the view.
6. **Attribute passthrough is sacred.** `hx-*`, `@click`, `aria-*`, `data-*`
   flow through untouched. Caller `class` merges after the component's own
   classes and is for layout only (width, grid placement), never to fight a
   component-owned property. Inside a component file, Alpine's `:class` and
   `:style` are written `::class` and `::style` (cotton's escape).
7. **Polymorphic where the element genuinely varies.** The buttons base
   renders `<a>` when `href` is set, `<button>` otherwise, with the two
   branches in lockstep in one file. Apply the same pattern only where the
   old macros had a real link twin.
8. **Declare props bare in `<c-vars>`** (`class` not `class=""`), which keeps
   djlint's empty-attribute rule meaningful for real markup. `<c-vars>` keys
   are excluded from `attrs`.
9. **Accessibility floor carries over**: `aria-label` required on icon-only
   controls, real elements for state (`disabled` on the button, never a
   styled sibling), focus-visible ring from the primary token on every
   interactive component.
10. **Keyframes and tokens stay in `tailwind.src.css`.** They are not
    component classes. Do not delete or edit any `tw-*` class: pages still
    consume them until page migration removes their last callers.

## Translating a `tw-*` family (how the buttons did it)

1. Read the family's `Component Classes -` banner section in
   `sbomify/assets/css/tailwind.src.css` and the old macro in
   `sbomify/apps/core/templates/components/tw/`, which holds the markup
   semantics (element, aria, conditional attrs).
2. Move shared structure to the base component's static class list. Anything
   set per variant or per state becomes the variant file's recipe or a
   conditional segment.
3. Translate declarations to utilities with identical computed values: same
   tokens, same numbers. `0.625rem 1.25rem` padding is `px-5 py-2.5`;
   `2.75rem` min-height is `min-h-11`; a bespoke radius is
   `rounded-[0.625rem]`. Pseudo-states map to `hover:` / `active:` /
   `focus-visible:` / `disabled:` utilities; a focus shadow overrides a
   variant shadow because the pseudo-class adds specificity.
4. Keep the visual result byte-identical. The e2e baselines are the referee
   and they must not move in this phase.

## Testing pattern

Each set ships a probe template
`sbomify/apps/core/templates/core/cotton_probes/<set>.html.j2` exercising
every component (variants, sizes, states, attr passthrough, slot nesting) and
a test file `sbomify/apps/core/tests/test_cotton_<set>.py` that renders the
probe once (module-scoped fixture) and pins: each variant's recipe marker, the
size/state segments and their non-conflict, forwarding of `hx-*`/`@click`,
slot content, and any polymorphic branch. Follow
`sbomify/apps/core/tests/test_cotton_buttons.py`.

## Gallery

Every set swaps its own demo section in
`sbomify/apps/core/templates/core/design_system.html.j2` to render through the
new components, exactly as the Buttons section does. Edit only your section;
the file is shared, so if an edit fails to match, re-read the file and retry.
Do not reformat the whole file. Keep `{% card %}` wrappers and other sets'
markup untouched: a set not yet componentized keeps its current demo.

## Verification ritual (per set)

```bash
uv run pytest sbomify/apps/core/tests/test_cotton_<set>.py sbomify/apps/core/tests/test_design_system*.py -q
uv run djlint sbomify/templates/components/<set> --extension=html --reformat
uv run djlint sbomify/templates/components/<set> --extension=html --lint   # 0 errors
uv run djlint <touched .j2 files> --reformat && uv run djlint <touched .j2 files> --lint
```

The full build, e2e suite, and both-theme gallery review run once over
everything at the end of the phase, not per set.

## Phase boundaries

In this phase: components, gallery swaps, probes, tests. Not in this phase:
migrating app pages, deleting `tw-*` CSS, porting the legacy date picker
(`sbomify/templates/components/date_picker.html.j2`, a Django template that
cotton ignores; leave it in place), or new visual design. If a faithful
translation is impossible without one of those, stop and record it in your
report instead.

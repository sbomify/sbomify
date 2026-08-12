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
   component-owned property. Cotton reads a leading `:` as its dynamic-prop
   prefix **on `<c-*>` tags only**, so Alpine's `:class` and `:style` there are
   written `::class` and `::style`; on plain HTML elements inside a component
   they need no escape and pass through untouched.
7. **Polymorphic where the element genuinely varies.** The buttons base
   renders `<a>` when `href` is set, `<button>` otherwise, with the two
   branches in lockstep in one file. Apply the same pattern only where the
   old macros had a real link twin.
8. **Declare props bare in `<c-vars>`** (`class` not `class=""`), which keeps
   djlint's empty-attribute rule meaningful for real markup. `<c-vars>` keys
   are excluded from `attrs`. With isolation on, a bare prop the caller omits
   is **undefined, not empty**: `{% if class %}` and `{{ class }}` are safe,
   but passing it as a **filter argument** (`"x-"|add:class`) raises
   `VariableDoesNotExist`. Branch with `{% if %}`, or normalise it first with
   `{% with extra=class|default:"" %}`.
9. **Accessibility floor carries over**: `aria-label` required on icon-only
   controls, real elements for state (`disabled` on the button, never a
   styled sibling), focus-visible ring from the primary token on every
   interactive component.
10. **Keyframes and tokens stay in `tailwind.src.css`.** They are not
    component classes. Do not delete or edit any `tw-*` class: pages still
    consume them until page migration removes their last callers.
11. **State the server cannot know goes on a data attribute, never on a
    class.** A row Alpine builds from JSON has no server-rendered variant to
    pick, so the component carries every recipe keyed by an attribute and the
    caller binds only the state. See "Runtime variants" below.

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

## Runtime variants: recipes stay in the component

Some values only exist in the browser. A table whose rows are built by Alpine
from `json_script` has no server render per row, so the server cannot choose
`c-badges.danger` over `c-badges.success`, and a client-side pager has no
current page for the view to mark active.

The wrong fix is to hand the page a class expression
(`:class="'tw-badge-' + variant"`): the recipe leaves the library, the legacy
class survives, and the two drift. The right fix is the one the sortable table
header already used: **the component owns every recipe, keyed by a data
attribute, and the caller binds only state.**

```html
{# The page: binds the value, never a class #}
<c-badges.dynamic ::data-variant="advisory.severity_variant"
                  x-text="titleCase(advisory.severity)" />

<c-navigation.page-button ::data-active="currentPage === page"
                          @click="goToPage(page)" x-text="page" />
```

```html
{# The component: every recipe, selected by the attribute #}
<span data-variant="{{ variant }}"
      class="… text-text-muted bg-[…border 30%…]
             data-[variant=danger]:text-danger data-[variant=danger]:bg-[…danger 12%…]
             data-[variant=success]:text-success …">{{ slot }}</span>
```

Three properties make this the pattern rather than a workaround:

- The resting classes are the fallback, so a value the component does not know
  (a new status from the server) renders neutral instead of unstyled.
- Native state uses the native attribute: `disabled` on a button gets
  `disabled:` utilities, not `data-disabled`. The look cannot drift from the
  state that drives it.
- Tailwind sees every recipe as a literal in the source, so it compiles. A
  computed class name never appears in the source and is never generated.

Current users: `c-badges.dynamic` (severity, status and publication in the
advisories list), `c-navigation.page-button` (client-paged tables), and
`c-tables.header-cell`'s sort carets (`data-sort`). Reach for a named variant
component every other time: `c-badges.danger` is clearer than a bound
attribute when the server knows the value.

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

## Building a page from the library

This is the playbook the migrated pages follow. `core/products_table.html.j2`,
`core/components_table.html.j2`, `core/releases_table.html.j2` and
`core/security_advisories_table.html.j2` are worked examples; read the nearest
one before starting.

**The target.** A page contributes data, layout and behaviour. Structure comes
from components. When you are done the template should contain no `tw-*`
class; if one is left, say why in your report rather than hiding it.

**1. Protect the page before you touch it.** If it has e2e coverage, that is
your referee. If it does not, add a snapshot test FIRST and run it, so the
baseline captures today's render:

```python
@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestThingListSnapshot:
    def test_thing_list_snapshot(self, authenticated_page, thing_fixture, snapshot, width):
        authenticated_page.goto("/things/")
        authenticated_page.wait_for_load_state("networkidle")
        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)
        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
```

Keep the test: the page gains the coverage it never had. Give the fixture
enough rows to reach a second page if the table pages, so the pager is covered.

**2. Read the components you are about to use**, not just this document. The
file is the parameter contract, and several take slots rather than params.

**3. Compose.** A table is the shell and its parts; a dialog is `c-modal` with
its actions in the `footer` slot. Alpine and HTMX attributes pass straight
through: keep `x-data`, `x-model`, `@click`, `hx-*` exactly as they were.

**4. Keep the data and behaviour identical.** Do not rewrite an Alpine
expression, rename state, or change what a view sends while migrating. One
kind of change at a time; the referee cannot tell you which change moved a
pixel.

**5. Verify, then read the diff images if anything moved.**

```bash
uv run djlint <touched .j2> --reformat && uv run djlint <touched .j2> --lint
bun run copy-deps && bun x vite build          # components changed → rebuild
docker compose -f docker-compose.tests.yml exec -T tests uv run python manage.py collectstatic --noinput
docker compose -f docker-compose.tests.yml exec -T tests uv run pytest <the page's e2e test> -q
uv run pytest sbomify/apps/core/tests/test_cotton_*.py sbomify/apps/core/tests/test_design_system*.py -q
```

### Traps these migrations actually hit

- **A card around a table double-frames it.** `c-tables.shell` draws its own
  surface, border and radius, and `c-cards.card` adds body padding, so the
  table that used to sit flush ends up inset. Use the shell alone; keep the
  card for the empty state, which does want padding.
- **Line-height drift.** Tailwind's `text-*` utilities carry a line-height;
  most old `tw-*` rules set only `font-size` and inherited 1.5. A component
  translated without `leading-[1.5]` renders 1-2px short per line, and the
  error compounds down a table. Where a component states its own line-height
  (`tw-chip-neutral` used 1.25), match that instead. If a migration shows rows
  creeping upward, this is why.
- **A missing component is a component, not an exception.** `+3 more` had nine
  callers and no component; the toolbar filter select had three. Build it,
  with its gallery demo and render test, rather than reaching for the legacy
  class.
- **The mobile viewport flips on a pixel.** At 375 a page that now fits the
  viewport loses its scrollbar, which widens the layout by ~5px and shifts
  sticky chrome you never touched. Confirm the content itself is unchanged
  before regenerating that baseline.
- **The browser caches error pages.** After fixing a template error, a stale
  500 page can persist; cache-bust the URL before concluding the fix failed.
- **Test pins are part of the change.** The render-contract tests pin exact
  recipe strings. If you correct a recipe, update its pin in the same commit;
  a failing pin is the test doing its job.

### What stays hand-rolled

Layout (grids, spacing stacks), one-off page copy, and genuinely unique
widgets. Compose those from utilities. The line: the moment markup looks like
a control, a container or a status chip, it belongs to the library.

## Phase boundaries

Not part of a page migration: deleting `tw-*` CSS (pages you have not migrated
still consume it), porting the legacy date picker
(`sbomify/templates/components/date_picker.html.j2`, a Django template cotton
ignores; leave it), redesigning anything, or changing view logic beyond the
context a component needs. If a faithful migration is impossible without one
of those, stop and record it in your report.

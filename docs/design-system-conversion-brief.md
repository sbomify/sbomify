# Brief: finish the design system conversion

Hand this to a fresh session. It assumes no memory of the work so far.

**To let the session orchestrate this, start your message with "use a workflow".**
The Workflow tool needs explicit opt-in per session and will otherwise refuse.

---

## The goal

Every page of the app front end pulls all of its UI from the shared component
library. Not "mostly" and not "the leaf components": if an element looks like a
button, a badge, a card, a form control, a table or a page header, its appearance
comes from the library and the page contributes only layout.

Branch: `feat/design-system-v2`. Contract: `docs/design-system.md`. Findings from
the last sweep: `docs/design-system-audit.md`. Living gallery: `/design-system/`
(DEBUG only).

## Scope

**In:** every template under `sbomify/apps/*/templates/` and `sbomify/templates/`.

**Out:** anything under a `trust_center/` path, and `*/emails/*`. The trust centre
pages need per-workspace branding, which the app library deliberately does not
model. Do not touch them. Public product pages that are *not* trust centre
(`workspace_public`, `product_releases_public`, `public_releases_list`,
`public_release_artifacts`) **are** in scope.

## Non-negotiables

From `docs/design-system.md`, which is the contract. Read it before editing.

1. **Never hand-roll what exists.** Check the inventory table first.
2. **Never recolour or resize a component with a utility.** See trap 1 below. Use
   an existing variant, or add one, or set the component's accent custom property
   (`--btn-accent`, `--badge-accent`, `--choice-accent`, `--stat-accent`, …).
3. **Three-caller rule.** A new component or variant needs three real callers.
   Two callers means parameterise an existing one. One means leave it on the page.
   The rule has been wrong once (`tw-metric-chip` was rejected on a bad regex and
   had 17 callers) so count by hand before rejecting.
4. **Every library change ships with a gallery demo** in
   `core/design_system.html.j2`, an entry in `GALLERY_SECTIONS`
   (`core/views/design_system.py`), and an inventory row in `docs/design-system.md`.
   The gallery must call the real component through its tag, never hand-rolled
   markup.
5. **Copy rule:** no em or en dash as punctuation anywhere a user reads. Short,
   plain words. See the Copy section of the contract.
6. **Never edit an existing migration. Never amend or force push.**

## Step 1: reproduce the audit before changing anything

Run this. It is the only search that finds the real problems, and the numbers tell
you whether the tree has moved since the audit was written.

```python
# python3 - <<'PY'
import re, pathlib, collections

CSS = "\n".join(p.read_text() for p in pathlib.Path("sbomify/assets/css").rglob("*.css"))
DEFINED = set(re.findall(r"\.(tw-[a-z0-9-]+)", CSS))
files = [p for p in pathlib.Path("sbomify").rglob("*.j2")
         if "trust_center" not in str(p) and "/emails/" not in str(p)]

COLOUR_OWNERS = ("tw-btn","tw-badge","tw-icon-btn","tw-icon-chip","tw-metric-chip","tw-stat-",
                 "tw-alert","tw-tag","tw-choice","tw-dropdown-item","tw-copy-btn","tw-form-",
                 "tw-page-header-title","tw-page-header-subtitle","tw-data-label")
BOX_OWNERS = ("tw-btn","tw-badge","tw-card","tw-icon-btn","tw-icon-chip","tw-choice",
              "tw-dropdown-item","tw-copy-btn","tw-metric-chip","tw-data-table-toolbar",
              "tw-data-table-footer")
CU = re.compile(r"^(?:bg-(?!transparent$)|text-(?!xs$|sm$|base$|lg$|xl$|\d?xl$|left$|right$"
                r"|center$|justify$|nowrap$|ellipsis$|wrap$|balance$)|border-(?!0$|\d+$|t$|b$"
                r"|l$|r$|x$|y$|solid$|dashed$|none$)|from-|to-|via-)")
BU = re.compile(r"^(?:p|px|py|pt|pb|pl|pr)-[\d.]|^rounded")

conflicts, shapes = [], collections.Counter()
for path in files:
    text = path.read_text()
    for m in re.finditer(r'class="([^"]*)"', text):
        cl = [c for c in m.group(1).split() if not c.startswith(("{", "}"))]
        tw = [c for c in cl if c.startswith("tw-")]
        ut = [c for c in cl if not c.startswith("tw-")]
        line = text.count("\n", 0, m.start()) + 1
        if tw:
            bad = [u for u in ut
                   if (CU.match(u) and any(t.startswith(COLOUR_OWNERS) for t in tw))
                   or (BU.match(u) and any(t.startswith(BOX_OWNERS) for t in tw))]
            if bad:
                conflicts.append((str(path), line, tw[:2], bad[:3]))
        else:
            rnd = any(c.startswith("rounded") for c in cl)
            pad = any(re.match(r"^(p|px|py)-[\d.]", c) for c in cl)
            bg = any(c.startswith("bg-") for c in cl)
            if rnd and pad:
                shapes["button-or-control shape, no component"] += 1
            elif rnd and any(c.startswith("border-border") for c in cl):
                shapes["card-or-panel shape, no component"] += 1
            elif rnd and bg:
                shapes["badge-or-chip shape, no component"] += 1

print(f"conflicts: {len(conflicts)}")
for c in conflicts[:40]:
    print(f"  {c[0]}:{c[1]}  {' '.join(c[2])}  <-  {' '.join(c[3])}")
print(dict(shapes))
print("undefined tw-* names:",
      sorted(c for f in files for c in re.findall(r"tw-[a-z0-9-]+", f.read_text())
             if c not in DEFINED and not c.endswith("-")))
# PY
```

At the time of writing: **conflicts 5** (all detector limits, see the audit),
inputs done, and roughly **69 buttons, 95 badges, 239 panels** still hand-rolled.
If conflicts is not ~5, something regressed and that comes first.

## Step 2: the work, in order

1. **Buttons (~69, 34 files).** `<button>` with its own `rounded-*` and padding.
   Target: `tw-btn-*` with `tw-btn-sm`/`-lg`, or `tw-icon-btn` (+ `-sm`, `-danger`,
   `-primary`, `-success`, `-stretch`) for icon-only, or `tw-dropdown-item` inside
   a menu. Worst files: `controls/settings_tab.html.j2`,
   `core/components/header.html.j2`, `compliance/cra_step_4.html.j2`,
   `core/components/pagination_controls.html.j2` (that last one should probably be
   the `pagination` component or `table_pager`).
2. **Badges and chips (~95, 39 files).** A `rounded` `bg-*` span at `text-xs`.
   Target: `tw-badge-*` (+ `-sm`, `-severity-{critical,high,medium,low}`),
   `tw-tag-*`, `tw-metric-chip`, `tw-icon-chip`. Worst files:
   `controls/components/public_controls_catalog.html.j2`,
   `vulnerability_scanning/vulnerability_scans.html.j2`,
   `core/product_details_private.html.j2` (its vulnerability counts are four
   hand-rolled severity pills and should be `tw-badge-severity-*`).
3. **`contact_profiles/` as one job.** `teams/contact_profiles/` has its own
   `entity-card` class and never went through any conversion. Do it as a unit, not
   line by line.
4. **Table shells.** Five secondary tables still hand-roll the toolbar:
   component detail, release artifacts, component vulnerabilities, CBOM issues,
   component item. Target shape, which the four list tables already use:
   ```html
   <div class="tw-card">
     <div class="tw-data-table">
       <div class="tw-data-table-toolbar">…</div>
       <div class="tw-data-table-container"><table class="tw-table">…</table></div>
       <div class="tw-data-table-footer">…</div>
     </div>
   </div>
   ```
5. **Detail page headers.** Product, component and release detail still build
   their own header. Target: `{% page_header title=… subtitle=… icon=… %}` with
   the visibility selector and actions as block content. It must sit **above** the
   page's content stack, never inside it, or it gets the gap twice.
6. **Remaining "Actions" columns (~13 tables).** Target: `tw-table-actions` on th
   and td, an `sr-only` label instead of visible text, and `{% actions_menu %}` for
   the controls. `core/products_table.html.j2` and
   `core/product_details_private.html.j2` are the reference.
7. **Panels (~239).** Judgement per case. A bordered box is not automatically a
   card. Convert the ones that are a card, a data table shell, or a
   `tw-select-row`; leave genuine one-off boxes and say so in the report.
8. **Leftovers.** `rgb(var(--token))` still exists in app-level CSS outside
   `tailwind.src.css` (the 13 in the main sheet are fixed). Visible em dashes have
   not been swept (287 occurrences across 90 templates, most inside
   `{% comment %}` where the rule does not apply).

## Step 3: how to verify. All of it, every time

```bash
# Templates: reformat then check. CI checks formatting, not just lint.
uv run djlint . --extension=j2 --reformat && uv run djlint . --extension=j2 --check

# Python
uv run ruff check . --fix && uv run ruff format . && uv run mypy .

# Frontend
bun test
bun lint
bun x tsc --noEmit --skipLibCheck -p tsconfig.app.json

# Python tests (always in Docker)
docker compose -f docker-compose.tests.yml up -d
docker compose -f docker-compose.tests.yml exec -T tests uv run pytest \
  --ignore=sbomify/apps/core/tests/e2e -q

# Visual regression. Build first or you are testing the old CSS.
bun run copy-deps && bun x vite build
docker compose -f docker-compose.tests.yml exec -T tests uv run pytest \
  sbomify/apps/core/tests/e2e -q
```

The visual suite is the real safety net for this work. Baselines live in
`sbomify/apps/core/tests/e2e/__snapshots__/` at widths 375, 576, 992, 1920; diffs
land in `__diffs__/`. **Read every diff image before regenerating its baseline**,
and say in the commit message what moved and why. A suite that is green because
you regenerated without looking is worth nothing.

Also read the pages in a browser. Local dev: `./bin/developer_mode.sh up` (see
trap 14), then `http://localhost:8000`. Check both themes: dark mode is a `.dark`
class on `<html>`.

## Traps that have already cost time

These are all real, all hit on this branch, and most fail **silently**.

1. **A utility cannot beat a component class.** The `tw-*` classes are unlayered
   and emitted after Tailwind's utilities, so at equal specificity the component
   wins. `class="tw-stat-value text-danger"` renders in the default colour and
   nothing warns you. This is the single most common defect in the app.
2. **Two variants of one family fight, and declaration order decides.**
   `tw-btn-secondary` with `tw-btn-success` renders as secondary, because
   secondary is declared later. Never stack variants.
3. **`:not()` counts as a class for specificity.**
   `.tw-table-fixed th:not(:first-child):not(:last-child)` outranks
   `.tw-table td.tw-cell-end`. Fix by excluding the explicit case from the
   automatic rule, not by escalating specificity.
4. **`rgb(var(--color-x))` is invalid.** The tokens are already `rgb(…)`, so the
   whole declaration is dropped. Use the token directly, or
   `color-mix(in oklab, var(--color-x) 12%, transparent)` for a tint.
5. **A `{# … #}` comment over more than one line renders as page text.** Django's
   tag pattern is not multi-line. Inside a tag it becomes junk attributes. Use
   `{% comment %}…{% endcomment %}`.
6. **`{{ var }}` does not interpolate inside a tag argument.**
   `{% actions_menu label="Actions for {{ row.name }}" %}` renders the braces.
   Pass a variable, or build it with `{% with x="a"|add:row.name %}`.
7. **`$nextTick` does not fire from inside an `Alpine.data` method.** Use
   `setTimeout(fn)`. Measuring forces layout anyway, so there is nothing to wait
   for a paint for.
8. **`requestAnimationFrame` and `x-transition` are frozen in a background tab.**
   A menu positioned in rAF stays invisible; an `x-transition` sticks at its enter
   state. Prefer CSS animation for entrances. This also means browser automation
   in an unfocused tab will lie to you: check `document.visibilityState`.
9. **`overflow-x: auto` clips both axes.** `tw-data-table-container` scrolls, so a
   menu positioned inside a row is cut off. That is why `actions_menu` teleports to
   the body and positions itself against the trigger, and why it closes on scroll.
10. **Delete e2e baselines with Python, not a shell loop.** In zsh,
    `"$base[$w].jpg"` is array subscripting and silently deletes nothing, so the
    suite keeps failing against the old baseline and you chase a ghost. The suite
    creates a baseline when the file is absent and passes.
11. **Never set `custom_blocks` in djlint config.** It hangs the formatter.
12. **bandit:** `# nosec B308,B703` does not suppress B308 on `mark_safe`. Use a
    bare `# nosec` with a comment above it explaining why the HTML is trusted.
13. **`bun run copy-deps` rewrites `sbomify/static/webfonts/*` and
    `static/css/fontawesome.min.css`.** Unrelated to your change. `git restore`
    them before committing.
14. **Start Docker with `./bin/developer_mode.sh up`.** A plain `docker compose up`
    loses `DEBUG:-True`, so `SECURE_SSL_REDIRECT` 301s every page, and it can
    spawn a second backend replica.
15. **Screenshot coordinates are scaled** relative to CSS pixels
    (screenshot width ÷ `window.innerWidth`, about 1.037 here). Read
    `getBoundingClientRect()` and scale, or click programmatically.
16. **A class that does not exist fails silently.** Grep every new class name in
    `tailwind.src.css` before shipping it, and remember class names also come from
    `.ts` files.

## The tag API, in one place

```jinja
{% load design_system %}

{# leaf tags #}
{% button text="Save" variant="primary" size="sm" icon="fas fa-check" %}
{% input name="title" label="Title" hint="Shown under the field" required=True %}
{% badge text="Draft" variant="secondary" %}
{% choice_group name="severity" label="Severity" options=severity_options selected="medium" %}

{# block tags: card, modal, actions_menu, page_header #}
{% card title="Releases" variant="dashboard" %}
    {% badge text="3 overdue" variant="danger" %}
{% endcard %}

{% page_header title="Products" subtitle="Your products." icon="fas fa-cube" %}{% endpage_header %}

{% actions_menu label="Product actions" width="w-56" %}
    <a href="…" role="menuitem" class="tw-dropdown-item no-underline">…</a>
{% endactions_menu %}
```

Any kwarg prefixed `aria_`, `data_`, `hx_`, `x_` becomes the dashed attribute.
Alpine's `@click` and `:class` go through `attrs` as a trusted raw string.
Registered tag names are the file names in
`sbomify/apps/core/templates/components/tw/`. New Alpine components register in
`sbomify/apps/core/js/alpine-components.ts` via `registerAlpineComponent`.

## Suggested workflow shape

Keep it to the session's size guideline unless the user raises it. Phases, in
order, with a human-readable result from each:

1. **Discover.** One agent per category from step 2. Each returns a verified
   work-list: file, line, current markup, proposed target, and a flag for anything
   that cannot be converted with a reason. No edits in this phase.
2. **Decide the library surface.** One synthesis agent reads all the work-lists
   and proposes the minimal set of new variants, applying the three-caller rule
   and naming them the way the existing families are named. **Stop here and show
   the user this list before any template is edited.** Every conflict fixed on
   this branch turned out to be a missing variant, so getting this list right is
   most of the work.
3. **Extend the library.** One agent: CSS variants, gallery demos, `GALLERY_SECTIONS`
   entries, inventory rows in the contract. Verify in the gallery in both themes.
4. **Convert.** Pipeline over files, not categories, so one file is edited by one
   agent. Use `isolation: "worktree"` only if two agents would touch the same file.
   Each agent runs djlint on what it touched.
5. **Verify.** The full command list above, then read every moved baseline image
   and every page touched in the browser.
6. **Report.** What converted, what was deliberately left and why, what the sweep
   says now. The "deliberately left" list is not failure, it is the deliverable's
   honest edge.

## Definition of done

- The sweep reports **zero** conflicts that are not detector limits, and each
  remaining limit is named with its reason.
- Every hand-rolled instance from step 2 is either converted or listed with a
  reason.
- Every new variant has a gallery demo, a `GALLERY_SECTIONS` entry and an
  inventory row in `docs/design-system.md`.
- djlint, ruff, mypy, `bun test`, `bun lint`, `tsc` all clean.
- The full e2e suite green, with every moved baseline reviewed and the reason for
  each stated in the commit.
- Pages read in the browser in both themes, mobile width included.

## Commit conventions

Conventional commits, one per phase. Explain the *why*, name what you verified,
and list what you left undone. End with:

```
Co-Authored-By: Claude <noreply@anthropic.com>
```

Never amend, never force push. Use `gh` for GitHub; `gh pr edit` can fail on a
Projects-classic deprecation error, in which case use `gh api -X PATCH`.

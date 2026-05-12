# 7. Remove the Project Layer

Date: 2026-05-12

## Status

Accepted

## Context

sbomify's workspace hierarchy was designed in 2024 as four levels:

```
Workspace (Team) → Product → Project → Component → SBOM / Document
```

The intent was that a `Product` (the thing the customer ships) could be
sliced into one or more `Project`s (logical groupings like "Backend",
"IoT Device", "Compliance Docs"), each containing related `Component`s
(individual code repos with their own SBOMs). The Project layer was
expected to give customers an extra organisational dimension and to act
as an aggregate boundary for sharing — a tenant could mark a single
project public without exposing the whole product.

In practice, three things happened over the next 18 months that
undermined the layer's value:

1. **Customers didn't use projects as a grouping primitive.** Most
   workspaces in production had exactly one Project per Product, named
   the same as the parent. The intermediate aggregate cost users a
   click without giving them a meaningful organisational handle.

2. **The aggregate boundary leaked.** `Project.is_public` was the only
   field that lived solely at the Project level, and it intersected
   with `Product.is_public` and `Component.visibility` in a way that
   was opaque to most users. The resulting "what's visible to whom"
   matrix had four state combinations per (product, project, component)
   triple, and every component-listing view in the codebase had to
   re-implement the same join. The destructive migration commentary in
   `sbomify/apps/sboms/migrations/0062_*.py` documents the awkwardness
   of preserving these semantics through the removal.

3. **The Project model was relabeled "Legacy" in commit `c28abad9`
   (September 2025).** The intent at that point was to remove the
   layer, but the surface area was never trimmed. The codebase carried
   roughly 200 files that referenced Project — half of them in tests,
   half in dead view/template/API paths — for nine months.

## Decision

Collapse the hierarchy to three levels:

```
Workspace (Team) → Product → Component → SBOM / Document
```

`Component`s attach to `Product`s directly via a `ProductComponent` M2M
(declared on `Component.products` with `Product.components` as the
reverse accessor). The `Project` model, `ProductProject` and
`ProjectComponent` through tables, the `/api/v1/projects/*` API surface,
all project-related views/URLs/templates/sidebar entries, and
`BillingPlan.max_projects` are deleted in a single PR.

There is **no backward-compatibility layer.** This is a deliberate hard
break — the maintainer confirmed no external API consumers exist outside
the two first-party repos (`sbomify-action` and `sbomify.com`), both of
which are updated in lockstep.

### Visibility cascade rule (post-PR)

A component appears on the public trust center iff:

```
Product.is_public = True
AND Component.visibility ∈ {PUBLIC, GATED}
```

This is strictly simpler than the pre-PR rule, which required a
public Project as an additional gate. The migration `0062` performs a
one-time visibility demotion: components that would have been hidden
behind a private project pre-PR but would now become visible are
demoted to `PRIVATE` to preserve the pre-existing listing surface area.

### `Component.is_global` semantic

Pre-PR, `Component.is_global=True` meant "workspace-scoped, not in any
project." Post-PR, it means "workspace-scoped, not attached to any
product." The constraint that only DOCUMENT-type components may be
global is now enforced at the model layer (in `Component.clean()`) in
addition to the existing API-layer check. Setting `is_global=True` on a
component that has products attached now detaches them in the same
`save()` call.

## Migration strategy

Eight phases, all in one PR:

1. **Additive schema.** Add `ProductComponent` through model + the
   `Component.products` M2M. Both old and new linkage coexist.
   (`sboms.0059`)
2. **Backfill.** Non-atomic data migration backfilling rows from the
   legacy chain (`Product → ProductProject → Project → ProjectComponent
   → Component`) into `ProductComponent`. Pre-filters cross-tenant pairs
   in SQL. Idempotent via `unique_together` + `ignore_conflicts=True`.
   (`sboms.0060`)
3. **Read-side rewrite.** All cross-traversal queries (`Component.objects.filter(projects__products=…)`)
   replaced with the direct `Component.objects.filter(products=…)`.
4. **Write-side and API.** `project_ids` field on `PATCH /products`
   becomes `component_ids`. The `/api/v1/projects/*` endpoints are
   deleted. Sidebar, dashboard, project views/templates/URLs all gone.
5. **Test sweep.** ~36 project-specific test files deleted; ~70
   fixture-only files rewritten.
6. **Destructive schema.** Drops the `Project` / `ProductProject` /
   `ProjectComponent` tables and the legacy M2M fields, after a
   one-time visibility demotion to preserve pre-PR public-listing
   semantics. Runs `atomic=False` so the long `UPDATE` commits before
   the schema-altering ops take heavy locks. (`sboms.0062`)
7. **Proxy & signal cleanup.** Remove `core.models.Project` proxy and
   the bridge `m2m_changed` signal that previously mirrored legacy
   rows into the new M2M. (`core.0026`)
8. **Billing limit cleanup.** Drop `BillingPlan.max_projects`.
   (`billing.0011`)

## Consequences

### Positive

- **Surface-area reduction.** Net ~470 lines deleted across
  `core/apis.py`, `sboms/utils.py`, and `sboms/builders.py`. Visibility
  logic is one rule rather than four state combinations.
- **One fewer click to organise a workspace.** New users no longer have
  to create a redundant Project before attaching components to a
  product.
- **Tenancy enforcement is in three layers, each tested.** M2M
  `pre_add` signal, through-model `clean()` + `save()`, and the
  backfill SQL filter. See
  `sbomify/apps/sboms/tests/test_product_component_tenancy.py`.
- **API surface shrinks.** Six CRUD endpoints + one download endpoint
  removed; one field on `PATCH /products` (`project_ids` → `component_ids`).

### Negative

- **One-way migration.** Migration `0062`'s visibility demotion is
  `RunPython.noop` on reverse — the rollback path is database restore
  from a pre-deploy snapshot. The PR description and `CHANGELOG.md`
  document this.
- **Lost organisational dimension.** Customers who genuinely used
  Projects as a grouping primitive lose that handle. The mitigation is
  that Components remain attachable to multiple Products (the new M2M
  is many-to-many in both directions), which preserves the use case of
  "this Compliance component lives under every Product".
- **Multi-product components with conflicting historical visibility.**
  Pre-PR, a component could be listed under one product (via a public
  project) and hidden under another (via a private project). Post-PR,
  the per-component `visibility` scalar is the only knob. The
  destructive migration applies a "safer-of-the-two" rule (leave
  visible if visible somewhere pre-PR) and emits no per-tenant report;
  operators of tenants with this pattern should review.

## References

- PR sbomify/sbomify#946 — the implementation
- PR sbomify/sbomify.com#90 — companion marketing-site doc rewrite
- Commit `c28abad9` (September 2025) — when the layer was first labelled
  "Legacy"
- ADR-0006 — Generalized BOM Model (the artifact-typing decision this
  refactor leaves untouched)
- `sbomify/apps/sboms/migrations/0062_remove_product_projects_remove_project_products_and_more.py`
  — preamble documents the visibility-demotion precedence rule
- `sbomify/apps/sboms/tests/test_product_component_tenancy.py` —
  three-layer cross-tenant invariant tests
- `CHANGELOG.md` — operator-facing breaking-change record

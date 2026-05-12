# Changelog

All notable changes to sbomify will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Breaking changes — data model

The Project layer has been removed from the workspace hierarchy. The model goes from

```text
Workspace (Team) → Product → Project → Component → SBOM / Document
```

to

```text
Workspace (Team) → Product → Component → SBOM / Document
```

Components now attach directly to Products via a `ProductComponent` M2M.

#### What was removed

- The `Project` Django model and its `ProductProject` / `ProjectComponent`
  through tables (`sboms.0062_remove_product_projects_*`,
  `core.0026_delete_productproject_*`).
- The `BillingPlan.max_projects` JSONField limit
  (`billing.0011_remove_billingplan_max_projects`).
- The proxy classes for Project / ProductProject / ProjectComponent in
  `sbomify.apps.core.models`.
- The bridge `m2m_changed` signal that previously mirrored legacy through
  rows into the new M2M.
- All sidebar / dashboard / breadcrumb references to Projects.

#### Removed API endpoints

These return HTTP 404 from this release onwards:

- `GET /api/v1/projects/`
- `POST /api/v1/projects/`
- `GET /api/v1/projects/{id}/`
- `PUT /api/v1/projects/{id}/`
- `PATCH /api/v1/projects/{id}/`
- `DELETE /api/v1/projects/{id}/`
- `GET /api/v1/projects/{id}/download/`

#### Changed API endpoints

- `PATCH /api/v1/products/{id}/` — the `project_ids` field is replaced with
  `component_ids` (assign/unassign components directly).
- `GET /api/v1/products/` and `GET /api/v1/products/{id}/` no longer return
  a `project_count` field.

#### Changed semantics

- `Component.is_global` now means **"workspace-scoped, not attached to any
  product"**. The constraint that only DOCUMENT-type components may be
  global is now enforced both at the API layer AND in `Component.clean()`.
- Setting `is_global=True` on a component that has products attached now
  detaches them in the same `save()` call (previously this was duplicated
  across four call sites and was easy to forget).
- **Public listing rule:** components appear on the trust center iff
  `Product.is_public=True AND Component.visibility ∈ {PUBLIC, GATED}`.
  Migration `sboms.0062` performs a one-time, irreversible visibility
  demotion to preserve the pre-existing listing semantics for components
  that were previously hidden behind a private project. See the migration
  preamble for the exact rule.

#### Migration ordering

Migrations apply in this order; the destructive ones (`0062` and `0026`)
hard-delete the legacy tables:

1. `sboms.0059_add_productcomponent` — adds the new M2M
2. `sboms.0060_backfill_productcomponent` — non-atomic backfill,
   pre-filters cross-tenant pairs, idempotent via
   `unique_together` + `ignore_conflicts=True`
3. `sboms.0061_remove_productcomponent_…_idx` — removes a redundant index
4. `core.0026_delete_productproject_…` — drops the proxy state
5. `sboms.0062_remove_product_projects_…` — **non-atomic destructive** —
   demotes visibility, then drops `Project`, `ProductProject`,
   `ProjectComponent` tables and the `Product.projects` /
   `Component.projects` columns
6. `sboms.0063_alter_productcomponent_unique_together_and_more` — final
   constraint adjustments
7. `billing.0011_remove_billingplan_max_projects`
8. `sboms.0064_alter_component_is_global` — refreshes the `help_text` on
   `Component.is_global` to document the new "workspace-scoped /
   DOCUMENT-only" semantics (text-only change, no DB schema impact)

#### Rollback

Migration `0062` and `0060` declare `RunPython.noop` for their reverse,
so neither data migration is reversible. To roll back:

1. Restore the database from a pre-deploy snapshot.
2. `manage.py migrate sboms 0058`
3. `manage.py migrate core 0025_unique_sbom_per_component_release`
4. `manage.py migrate billing 0010`

Coordinate with infra to retain the pre-deploy database dump for at least
the deprecation window.

#### Action required for integrators

- **`sbomify-action` (GitHub Action):** audited; already uses
  `/api/v1/components/...` — no changes required.
- **`sbomify.com` (marketing site):** rewritten in companion PR — drops
  Project references from feature docs, FAQ, pricing, and architecture
  diagrams.
- **Third-party API consumers:** the maintainer has confirmed there are
  no external consumers of `/api/v1/projects/*` besides the two
  first-party repos above. If your integration calls these endpoints,
  it will break — migrate to `PATCH /api/v1/products/{id}/` with the new
  `component_ids` field.

### Notable internal changes

- Migration `sboms.0062` runs `atomic=False` so the long visibility
  `UPDATE` commits before the `RemoveField` / `DeleteModel` schema ops
  take `ACCESS EXCLUSIVE`. This keeps lock duration bounded on large
  tenants during a rolling deploy.
- Both `m2m_changed` receivers on `sboms.ProductComponent` now declare
  `dispatch_uid` to prevent duplicate registration under
  `--reuse-db` / Gunicorn prefork / Dramatiq worker reload.
- `sbomify-worker` and `sbomify-scheduler` services now
  `depends_on: sbomify-migrations: service_completed_successfully` —
  workers wait for migrations before starting, preventing
  `ProgrammingError` against dropped legacy tables during a rolling deploy.
- Cross-tenant rejection of `Product↔Component` M2M operations is
  enforced at three independent layers (signal `pre_add`, through-model
  `clean()`/`save()`, and the backfill's same-team SQL filter). All three
  layers now have explicit test coverage in
  `sboms/tests/test_product_component_tenancy.py`.

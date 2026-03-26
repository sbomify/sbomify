# 7. Remove Project Hierarchy Level

Date: 2026-03-23

## Status

Proposed

## Context

sbomify's domain hierarchy is currently:

```text
Workspace (Team) → Product → Project → Component → Artifact
```

Products and Components are connected through Projects via two M2M junction tables (`ProductProject` and `ProjectComponent`). Every query that relates components to products must traverse a double-hop through both tables.

The Project entity was introduced as an organizational grouping layer between Products and Components. In practice, it has become a pass-through that adds complexity without providing unique business value:

1. **Already tagged as legacy.** The `Project`, `ProductProject`, and `ProjectComponent` models are marked as legacy in their docstrings — the codebase already treats them as deprecated.

2. **Pervasive double-hop queries.** The ORM pattern `projects__products=product` appears across many files. Every new feature that relates components to products must navigate this indirection, adding complexity and an extra JOIN per query.

3. **Onboarding scaffolding.** The onboarding wizard auto-creates a "Main Project" just to wire products and components together — not because users need it.

4. **Redundant visibility model.** Projects have a simple `is_public` flag while Components already have a richer `Visibility` enum with `GatingMode`. The project-level visibility adds asymmetric constraints without adding capability.

5. **Significant code surface for no unique logic.** Projects account for models, junction tables, API endpoints, schemas, views, templates, URL routes, signals, billing limits, and onboarding code — none implementing logic that requires an intermediate entity.

## Decision

**Remove the Project entity. Replace the two-hop Product ↔ Project ↔ Component relationship with a direct Product ↔ Component many-to-many.**

The simplified hierarchy becomes:

```text
Workspace (Team) → Product → Component → Artifact
```

A `ProductComponent` through table replaces the `ProductProject` + `ProjectComponent` pair. All existing relationships are preserved — if a component was reachable from a product through any project, it becomes directly linked to that product.

### What Changes

- **Domain model**: One fewer hierarchy level. Products relate directly to Components.
- **API surface**: `/api/v1/projects/` endpoints are deprecated and eventually removed. Component assignment moves to Product endpoints.
- **Visibility**: Product and Component visibility rules apply directly. The intermediate project visibility layer is removed.
- **Billing**: `max_projects` limit removed. Product and component limits remain.
- **Onboarding**: Wizard creates Product and Component directly.

### What Stays the Same

- Product and Component models, their APIs, views, and templates are unchanged.
- Components can still belong to multiple Products (M2M), and Products can still contain multiple Components.
- Artifact storage, plugin assessments, vulnerability scanning, and release management continue to work.

## Migration Strategy

Four phases, each independently deployable:

1. **Add direct M2M** — Create `ProductComponent` through table. Data migration collapses two-hop relationships into direct links. Both old and new paths coexist.
2. **Deprecate project APIs** — Add `Deprecation` and `Sunset` headers ([RFC 8594](https://www.rfc-editor.org/rfc/rfc8594)) to `/api/v1/projects/` endpoints. Publish migration guide. Minimum 2 release cycles before removal.
3. **Switch internal code** — Replace all `projects__products` ORM lookups with direct `products` lookups. Update signals, billing, onboarding, and breadcrumbs.
4. **Remove project infrastructure** — Delete models, endpoints, schemas, views, templates, routes, and drop database tables. Add `410 Gone` or redirects for old URLs.

## Consequences

### Positive

- **Simpler domain model.** Users reason about "which components are in this product" without an intermediate grouping concept.
- **Reduced code surface.** Fewer models, endpoints, schemas, views, templates, and tests to maintain.
- **Simpler queries.** Every component-to-product query drops one JOIN.
- **Cleaner visibility model.** Asymmetric project-level constraints disappear.
- **Less onboarding friction.** No need to explain "projects" or auto-create placeholder objects.

### Negative / Tradeoffs

- **Breaking API change.** External consumers of `/api/v1/projects/` must migrate. Mitigated by the deprecation period.
- **Loss of sub-product grouping.** Users who organize components into named groups within a product lose that capability. If the need arises later, a lightweight tagging feature can be designed from actual requirements.
- **Migration effort.** Four-phase migration touches many files and requires careful data migration. Non-destructive phasing reduces risk but extends timeline.
- **URL breakage.** Existing bookmarks to `/project/<id>/` will stop working. Mitigated by `410 Gone` or redirects.

## Alternatives Considered

### 1. Keep Projects but Hide Them

Auto-create a transparent "default project" per product, hide all project UI.

**Rejected:** All code complexity remains — double-hop queries, junction tables, signal handlers, visibility constraints. This trades user-facing simplicity for continued internal complexity.

### 2. Replace Projects with Tags/Labels

Remove Projects, add tagging to Components for sub-product grouping.

**Rejected:** Requires building an entirely new feature, adding scope to what should be a simplification. Better pursued as a future enhancement designed from actual user requirements.

### 3. Do Nothing

**Rejected:** The double-hop pattern continues to spread. The "legacy" label on the models becomes increasingly misleading without action. Maintenance cost is ongoing and compounds.

## References

- [ADR-006: Generalized BOM Model with Type Discriminator](0006-generalized-bom-model.md) — documents the current domain hierarchy
- [RFC 8594: The Sunset HTTP Header Field](https://www.rfc-editor.org/rfc/rfc8594) — standard for communicating API deprecation

# 7. Remove Project Hierarchy Level

Date: 2026-03-23

## Status

Proposed

## Context

sbomify's domain hierarchy is currently four levels deep:

```text
Workspace (Team) → Product → Project → Component → Artifact
```

Products and Components are connected through Projects via two many-to-many junction tables: `ProductProject` (Product ↔ Project) and `ProjectComponent` (Project ↔ Component). This means every query that relates components to products must traverse a double-hop: `Component → ProjectComponent → Project → ProductProject → Product`.

The Project entity was introduced as an organizational grouping layer between Products and Components. In practice, it has become a pass-through that adds complexity without providing unique business value. Several indicators point to this:

1. **The models are already tagged as legacy.** The docstrings on `Project`, `ProductProject`, and `ProjectComponent` in `sboms/models.py` all say "Legacy model for data persistence only" — the codebase already treats them as deprecated infrastructure.

2. **The double-hop query pattern is pervasive.** The ORM pattern `projects__products=product` (or its inverse) appears in 16+ locations across 7 files — `core/models.py`, `core/apis.py`, `core/signals.py`, `vulnerability_scanning/apis.py`, `tea/apis.py`, `sboms/utils.py`, and `plugins/public_assessment_utils.py`. Every new feature that needs to relate components to products must navigate this indirection. It is a constant source of complexity and a performance overhead (one extra JOIN per query).

3. **The onboarding wizard auto-creates "Main Project."** When a user completes onboarding (`teams/views/onboarding_wizard.py`), the system creates a default product, a "Main Project", and a "Main Component", then wires them together. This scaffolding exists because the four-level hierarchy requires a project to connect products and components — it does not reflect intentional user choice.

4. **Project visibility is redundant.** Projects have a simple `is_public: bool` field. Components have a richer `Visibility` enum (`public`, `private`, `gated`) with `GatingMode` for access control. The project-level visibility is strictly less capable than what components already provide, yet it introduces asymmetric constraints (e.g., "Cannot make a project private if assigned to public products").

5. **The Release system treats Projects as transparent.** `Release.refresh_latest_artifacts()` queries `Component.objects.filter(projects__products=self.product)` — it only cares which components belong to the product. Projects are traversed but carry no semantic weight.

6. **Significant code surface for no unique logic.** Projects account for 3 model classes, 2 junction tables, 7 API endpoints, 6 schema classes, 3 views, 10+ templates, 8 URL routes (plus redirects), a signal handler, billing limit fields, breadcrumb logic, admin registration, and onboarding wizard code. None of this code implements business logic that couldn't be handled by a direct Product ↔ Component relationship.

### Current Code Surface

| Category | Count | Key locations |
| -------- | ----- | ------------- |
| Models | 3 models + 2 through tables | `sboms/models.py`, `core/models.py` (proxies) |
| API endpoints | 7 CRUD + 1 download | `core/apis.py` |
| Schemas | 6 classes | `core/schemas.py` |
| Views | 3 class-based views | `core/views/` |
| Templates | 10+ | `core/templates/` |
| URL routes | 8 + redirect routes | `core/urls.py`, `sboms/urls.py` |
| Signals | 1 handler | `core/signals.py` |
| Billing | `max_projects` field + limit checks | `billing/models.py`, `core/apis.py` |
| Tests | 100+ references | 30+ test files |

## Decision

**Remove the Project entity from the domain hierarchy. Replace the two-hop Product ↔ Project ↔ Component relationship with a direct Product ↔ Component many-to-many.**

The simplified hierarchy becomes:

```text
Workspace (Team) → Product → Component → Artifact
```

A new `ProductComponent` through table replaces the `ProductProject` + `ProjectComponent` pair. All existing relationships are preserved — if a component was reachable from a product through any project, it becomes directly linked to that product.

### What Changes

- **Query pattern**: `Component.objects.filter(projects__products=product)` becomes `Component.objects.filter(products=product)`. One JOIN eliminated.
- **API surface**: The 7 `/api/v1/projects/` endpoints are deprecated and eventually removed. Component assignment moves to the existing Product PATCH endpoint.
- **Visibility**: Product and Component visibility rules apply directly. The intermediate project visibility layer and its asymmetric constraints are removed.
- **Billing**: The `max_projects` limit is removed from billing plans. Product and component limits remain.
- **Onboarding**: The wizard creates a Product and a Component directly, without an intermediate "Main Project".
- **Aggregated SBOMs**: Project-level SBOM aggregation (`get_project_sbom_package`) is replaced by product-level aggregation, which already exists via `get_product_sbom_package`.

### What Stays the Same

- The Product and Component models, their APIs, views, and templates are unchanged.
- Components can still belong to multiple Products (M2M), and Products can still contain multiple Components.
- All artifact storage, plugin assessments, vulnerability scanning, and release management continue to work — they just traverse one fewer join.

## Migration Strategy

### Phase 1: Add Direct Product ↔ Component M2M (Non-Destructive)

Add a `ProductComponent` through table alongside the existing `ProductProject` and `ProjectComponent` tables. Write a data migration that collapses the two-hop relationships:

```sql
INSERT INTO product_component (product_id, component_id)
SELECT DISTINCT pp.product_id, pc.component_id
FROM product_project pp
JOIN project_component pc ON pp.project_id = pc.project_id
ON CONFLICT DO NOTHING;
```

At this point both paths exist — old code uses `projects__products`, new code uses `products`. No behavior change.

### Phase 2: Deprecate Project API Endpoints

Add `Deprecation` and `Sunset` HTTP headers to all `/api/v1/projects/` endpoints per [RFC 8594](https://www.rfc-editor.org/rfc/rfc8594). Publish a migration guide for API consumers explaining:

- How to replace `POST /projects` → assign components directly to products via `PATCH /products/{id}`
- How to replace `GET /projects/{id}` → use product endpoints with component listing
- How to replace project-level SBOM download → use product-level SBOM download

Duration: **2 release cycles** minimum before removal.

### Phase 3: Switch Internal Code to Direct M2M

Update all internal code paths to use the new `ProductComponent` relationship:

- Replace all `projects__products` and `projects__components` ORM lookups
- Update `Release.refresh_latest_artifacts()` signal to use `ProductComponent` M2M changed signal
- Simplify `Component.get_products()` from `Product.objects.filter(projects__components=self)` to `self.products.all()`
- Update breadcrumb logic to navigate Component → Product directly
- Remove `max_projects` from `BillingPlan` and all billing limit checks
- Simplify onboarding wizard to skip project creation
- Update dashboard summary endpoint to remove `project_id` filter parameter

### Phase 4: Remove Project Infrastructure

- Delete `Project`, `ProductProject`, `ProjectComponent` models (and proxy models)
- Remove all project API endpoints, schemas, views, templates, URL routes, admin registration
- Remove project-related signal handlers, service functions, and query optimizers
- Add `410 Gone` responses for old `/project/<id>/` and `/public/project/<id>/` URLs, or redirect to the parent product where determinable
- Drop `sboms_project`, `sboms_productproject`, and `sboms_projectcomponent` database tables via migration

## Consequences

### Positive

- **Simpler domain model.** Three levels instead of four. Users reason about "which components are in this product" without an intermediate grouping concept that most never actively use.
- **Reduced code surface.** Approximately 50 fewer files to maintain. Fewer models, endpoints, schemas, views, templates, and tests.
- **Simpler queries.** Every component-to-product query drops one JOIN. The double-hop pattern that appears in 16+ locations becomes a single-hop.
- **Cleaner visibility model.** Product and Component visibility rules are sufficient. The asymmetric project-level constraints disappear.
- **Less onboarding friction.** No need to explain "projects" to new users or auto-create placeholder objects.

### Negative / Tradeoffs

- **Breaking API change.** External consumers of `/api/v1/projects/` endpoints must migrate. Mitigated by the deprecation period in Phase 2, but still requires coordination and a published migration guide.
- **Loss of sub-product grouping.** Users who organize components into named groups within a product lose that capability. No evidence in the codebase or usage data suggests this is common, but it is a reduction in functionality. If the need arises later, a lightweight tagging or labeling feature can be added, designed from actual user requirements rather than inherited from the original architecture.
- **Migration effort.** The four-phase migration touches many files and requires careful data migration to collapse relationships without data loss. The non-destructive phasing reduces risk but extends the timeline.
- **URL and bookmark breakage.** Existing bookmarks and links to `/project/<id>/` will stop working. `410 Gone` or redirect responses mitigate this, but some external references may be affected.

## Alternatives Considered

### 1. Keep Projects but Hide Them

Auto-create a single transparent "default project" per product. Hide all project UI, remove project API endpoints, but keep the database tables and junction logic intact.

**Strengths:**

- No data migration needed
- No API breaking change (endpoints could be deprecated silently)
- Backward-compatible at the database level

**Weaknesses:**

- All the code complexity remains — the double-hop query pattern, the junction tables, the signal handlers, and the visibility constraints stay in the codebase
- New contributors must still understand the hidden layer when reading ORM queries
- "Hidden but present" infrastructure tends to accumulate bugs from neglect

**Why rejected:** This trades user-facing simplicity for continued internal complexity. The goal is to simplify both.

### 2. Replace Projects with Tags/Labels on Components

Remove the Project entity and add a `tags` M2M or JSONField to Component, allowing users to group components by arbitrary labels within a product.

**Strengths:**

- More flexible than the rigid Project hierarchy
- Familiar UX pattern (tagging)
- Could support filtering, search, and dashboard scoping

**Weaknesses:**

- Requires building an entirely new feature (tag management UI, API, filtering)
- Different semantics — tags are flat, projects were hierarchical
- Adds scope to what should be a simplification effort

**Why rejected:** This is a potential future enhancement, not a replacement. If sub-product grouping is needed, it should be designed from actual user requirements. Bundling it with project removal would delay the simplification.

### 3. Do Nothing

Keep the four-level hierarchy as-is.

**Strengths:**

- Zero risk, zero effort
- No API breaking changes

**Weaknesses:**

- The double-hop query pattern continues to spread as new features are added
- Every new developer must learn the Project concept and understand why it exists
- The "legacy" label on the models becomes increasingly misleading as time passes without action

**Why rejected:** The cost of maintaining the Project layer is ongoing and compounds. The models are already marked as legacy — this ADR proposes following through on that signal.

## References

- [ADR-006: Generalized BOM Model with Type Discriminator](0006-generalized-bom-model.md) — documents the current domain hierarchy
- [RFC 8594: The Sunset HTTP Header Field](https://www.rfc-editor.org/rfc/rfc8594) — standard for communicating API deprecation

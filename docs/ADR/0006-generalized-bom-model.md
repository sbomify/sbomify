# 6. Generalized BOM Model with Type Discriminator

Date: 2026-03-23

## Status

Proposed

## Context

sbomify currently models artifacts using two separate systems:

- **SBOM model** (`sboms_sboms` table): Stores Software Bills of Materials with fields for format, format version, PURL qualifiers, and file hashing. Each SBOM belongs to a Component with `component_type="sbom"`.
- **Document model** (`documents_documents` table): Stores compliance documents, security advisories, and other files with fields for document type, content type, file size, and compliance subcategory. Each Document belongs to a Component with `component_type="document"`.

By design, components are typed — a component is intended to hold *either* SBOMs *or* Documents, never both. In the current implementation this invariant is enforced on the document upload path (via `component_type="document"` filtering), while the SBOM upload path fetches the component by ID without checking `component_type`. The `ReleaseArtifact` model bridges this with two nullable foreign keys (`sbom` and `document`), enforcing mutual exclusion in `clean()`.

This design is reaching its limits because:

1. **New BOM standards are proliferating.** Beyond SBOM (CycloneDX, SPDX), the industry now has CBOM (Cryptography BOM), AIBOM (AI BOM), HBOM (Hardware BOM), SaaSBOM, OBOM (Operations BOM), and MBOM (Manufacturing BOM). Each uses the same underlying formats (CycloneDX, SPDX) but describes different aspects of a system.

2. **VEX doesn't fit cleanly into either model.** CycloneDX VEX documents are structurally CycloneDX BOMs (they have `specVersion`, `bomFormat`, components, and vulnerabilities). They share all the SBOM model's fields (format, format_version, hash, signature). Yet calling them "SBOMs" is semantically wrong. OpenVEX and CSAF are different formats entirely but serve the same purpose.

3. **Attestations live alongside BOMs, not in separate components.** An in-toto attestation or Sigstore bundle relates to a specific SBOM. Under the current model, the attestation would need to live in a different component (type=document) from the SBOM it attests (type=sbom), breaking the natural relationship.

4. **The two-model approach doesn't scale for `ReleaseArtifact`.** Every new artifact model would require another nullable FK on `ReleaseArtifact`, another uniqueness constraint, and updates to every piece of code that iterates release artifacts.

### Current Field Comparison

The SBOM and Document models share most of their fields:

| Field | SBOM | Document | Shared? |
| ----- | ---- | -------- | ------- |
| id (12-char token) | Yes | Yes | Shared |
| uuid | Yes | Yes | Shared |
| name | Yes | Yes | Shared |
| version | Yes | Yes | Shared |
| filename | `sbom_filename` | `document_filename` | Shared (different column name) |
| component (FK) | Yes | Yes | Shared |
| sha256_hash | Yes | Yes | Shared |
| signature_url | Yes | Yes | Shared |
| source | Yes | Yes | Shared |
| created_at | Yes | Yes | Shared |
| format | Yes | — | BOM-specific |
| format_version | Yes | — | BOM-specific |
| qualifiers (JSON) | Yes | — | BOM-specific |
| document_type | — | Yes | Document-specific |
| description | — | Yes | Document-specific |
| content_type | — | Yes | Document-specific |
| file_size | — | Yes | Document-specific |
| compliance_subcategory | — | Yes | Document-specific |

Ten shared fields versus 3 BOM-specific and 5 Document-specific. The type-specific fields are genuinely different in purpose: BOM fields describe format and build variants; Document fields describe content classification and compliance metadata.

## Decision

**Generalize the SBOM model with a `bom_type` discriminator field. Keep the Document model separate.**

### BOM Model Changes

Add a `bom_type` field to the existing SBOM model:

```python
class BomType(models.TextChoices):
    SBOM = "sbom", "SBOM"
    CBOM = "cbom", "CBOM"
    AIBOM = "aibom", "AI BOM"
    HBOM = "hbom", "HBOM"
    VEX = "vex", "VEX"
    SAASBOM = "saasbom", "SaaSBOM"
    OBOM = "obom", "OBOM"
    MBOM = "mbom", "MBOM"
```

The existing SBOM fields (`format`, `format_version`, `qualifiers`, `sha256_hash`, `signature_url`) apply naturally to all BOM types — a CBOM in CycloneDX format has the same structural metadata as an SBOM in CycloneDX format.

The unique constraint evolves from `(component, version, format, qualifiers)` to `(component, version, format, qualifiers, bom_type)`, allowing a component to hold both an SBOM and a VEX of the same format and version.

### Component Type Evolution

`Component.ComponentType` gains a `BOM = "bom"` value alongside the existing `SBOM = "sbom"` (retained for backward compatibility). A BOM-typed component can hold multiple BOM types simultaneously — an SBOM, a VEX, and a CBOM can coexist under one component.

### Document Model Unchanged

The Document model remains separate for non-BOM artifacts: compliance documents, attestation verification reports, security policies, penetration test reports, and other content that doesn't follow BOM format conventions. Its `document_type` taxonomy (20+ types with CycloneDX/SPDX reference mappings) is purpose-built for this classification.

### Classification Guideline

The boundary between BOM and Document:

- **BOM**: Any artifact that follows a structured BOM format (CycloneDX, SPDX) or is consumed/produced by BOM tooling. This includes SBOMs, CBOMs, AIBOMs, HBOMs, CycloneDX VEX, and similar machine-readable supply chain artifacts.
- **Document**: Everything else — human-readable reports, compliance certifications, policies, attestation verification results, unstructured security artifacts, and VEX statements that are not expressed as BOMs (e.g., OpenVEX or CSAF-based VEX documents).

When in doubt: if the artifact has `format` and `format_version` and is machine-parseable by BOM tools, it's a BOM. If it's primarily for human consumption or doesn't follow a BOM schema, it's a Document. Note: ADR-004's reference to "VEX statements" under Documents refers to these non-BOM VEX formats, whereas this ADR treats CycloneDX VEX (a BOM-structured format) as a BOM type.

### Why Not a Single Unified Model?

We considered merging SBOM and Document into one `Artifact` model (see Alternatives below). The BOM-specific fields (`format`, `format_version`, `qualifiers`) and Document-specific fields (`document_type`, `content_type`, `file_size`, `compliance_subcategory`) serve fundamentally different purposes. Merging them creates nullable columns that weaken database-level validation and make the model harder to reason about. The two-model approach preserves type safety where it matters while the `bom_type` discriminator handles the proliferation of BOM standards.

## Migration Strategy

### Phase 1: Model Foundation

- Add `BomType` enum and `bom_type` field to SBOM model (default: `"sbom"`, backfills automatically)
- Update unique constraint to include `bom_type`
- Add `BOM = "bom"` to `ComponentType` choices

### Phase 2: Service Layer and APIs

- Expose `bom_type` in schemas and API responses
- Add `bom_type` parameter to upload endpoints (default: `"sbom"` for backward compatibility)
- Update proxy model queries to group by `(format, bom_type)`

### Phase 3: Plugin System

- Pass `bom_type` context to assessment plugins
- Allow plugins to declare `supported_bom_types` so the orchestrator skips irrelevant BOM types
- Existing plugins (NTIA compliance, vulnerability scanning) declare support for `bom_type="sbom"` only

### Phase 4: UI

- BOM type selector on upload forms
- BOM type column/filter in artifact tables
- Component detail views handle mixed BOM types

### Deferred: Class and FK Renames

Renaming the `SBOM` class to `BOM`, renaming `ReleaseArtifact.sbom` FK to `bom`, and similar cosmetic changes are deferred to a separate effort once the functional changes are stable. These are high-risk migrations (touching FKs, indexes, and constraints across multiple apps) with no functional benefit.

## Consequences

### Positive

- **Scales with standards**: Adding CBOM, AIBOM, HBOM, or any future BOM type requires adding one enum value — no new models, tables, migrations with FK relationships, API routers, or templates.
- **Natural domain modeling**: A single component can hold its SBOM, VEX, and CBOM together, reflecting how supply chain artifacts actually relate to software.
- **Preserves type-specific validation**: BOM fields (format, version, qualifiers) remain non-nullable with proper constraints. Document fields (document_type, compliance_subcategory) remain in their own model with their own validation.
- **Backward compatible**: Existing SBOM records get `bom_type="sbom"` via default. Existing API consumers see no breaking changes. The `component_type="sbom"` value is retained alongside the new `"bom"` value.
- **Plugin-aware**: Plugins can opt into specific BOM types, preventing NTIA compliance checks from running on VEX documents.

### Negative / Tradeoffs

- **Classification decisions remain**: New artifact types still require a "BOM or Document?" decision, though the guideline (structured BOM format = BOM, everything else = Document) is clear for most cases.
- **`ReleaseArtifact` still has two FKs**: The `sbom`/`document` split on `ReleaseArtifact` persists. However, new BOM types don't add new FKs — they reuse the existing `sbom` FK since all BOMs live in the same table.
- **Naming debt**: The model class is still called `SBOM`, the app is still called `sboms`, and FK fields reference `sbom`. This is cosmetic debt that doesn't affect functionality but may confuse new contributors.
- **VEX format diversity**: CycloneDX VEX fits cleanly as a BOM (same format/version fields). OpenVEX and CSAF have different schemas — they'll need format-specific validation added to the upload pipeline.

## Alternatives Considered

### 1. Unified Artifact Model

Merge SBOM and Document into a single `Artifact` model with an `artifact_type` discriminator (e.g., `sbom`, `cbom`, `vex`, `compliance`, `attestation`).

**Strengths:**

- Single FK on `ReleaseArtifact` — no mutual exclusion logic
- "All artifacts for component" is one query, not a Python-level merge
- No classification boundary — every new type is just an enum value
- Eliminates the two-template, two-API-router, two-service pattern

**Weaknesses:**

- BOM-specific fields (`format`, `format_version`, `qualifiers`) become nullable for documents, and document-specific fields (`document_type`, `compliance_subcategory`, `content_type`) become nullable for BOMs. This weakens DB-level data integrity.
- The migration to merge two tables with different schemas, existing data, FK references from `ReleaseArtifact`, `ComponentReleaseArtifact`, `AssessmentRun`, and the TEA API is high-risk and high-effort.
- Type-specific behavior (CycloneDX/SPDX format mapping for BOMs, compliance subcategory badging for documents) requires runtime dispatch on `artifact_type`, losing the clarity of separate models.

**Why rejected:** The type-specific fields are genuinely different in kind, not just in name. The migration cost is substantial, and the primary benefit (single FK) doesn't justify it when the BOM table already absorbs all new BOM types.

### 2. Separate Model per Artifact Type (Status Quo++)

Add new `ComponentType` values (`vex`, `cbom`, `aibom`, etc.) and create separate models (VEX, CBOM, etc.) for each.

**Strengths:**

- Smallest code change per addition
- Maximum type safety — each model has exactly the fields it needs
- Clear separation in the database

**Weaknesses:**

- Every new BOM standard requires a new model, migration, FK on `ReleaseArtifact`, API router, upload endpoint, template, and service layer. The cost per type is linear and high.
- CycloneDX-based BOMs (SBOM, CBOM, VEX) would have near-identical models with the same fields, duplicating logic.
- `ReleaseArtifact` would need N nullable FKs for N artifact types.

**Why rejected:** Does not scale. The industry is producing new BOM types faster than we can add models.

## Relationship to Other ADRs

- **ADR-003 (Plugin-based Assessments)**: Plugins receive a BOM file path and produce `AssessmentRun` records. The `bom_type` field enables plugins to declare which BOM types they support, preventing irrelevant assessments.
- **ADR-004 (Immutable Security Artifacts)**: This decision doesn't change the immutability principle. All BOM types — SBOM, CBOM, VEX — are stored exactly as received. The `bom_type` field is metadata about the artifact, not a modification to it.

## References

- [ADR-003: Plugin-based Assessments for SBOM Uploads](0003-plugin-based-assessments-for-sbom-uploads.md)
- [ADR-004: Immutable Security Artifacts](0004-immutable-security-artifacts.md)
- [CycloneDX BOM Types](https://cyclonedx.org/) — SBOM, SaaSBOM, CBOM, AI/ML BOM, OBOM, MBOM, VEX
- [SPDX 3.0 Profiles](https://spdx.github.io/spdx-spec/v3.0/) — Software, AI, Dataset, Security (VEX)

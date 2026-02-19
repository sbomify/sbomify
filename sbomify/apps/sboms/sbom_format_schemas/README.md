# SBOM Format Schemas

This directory contains Pydantic models generated from official SBOM format schemas (CycloneDX and SPDX).

## Generating Schemas

We use [`datamodel-codegen`](https://github.com/koxudaxi/datamodel-code-generator) to generate Pydantic v2 models from JSON schemas.

### CycloneDX Schemas

To generate or update a CycloneDX schema:

```bash
# 1. Download the JSON schema
curl -o sbomify/apps/sboms/schemas/cdx_bom-X.Y.schema.json \
  https://raw.githubusercontent.com/CycloneDX/specification/refs/heads/master/schema/bom-X.Y.schema.json

# 2. Generate the Pydantic model (outputs to temp directory due to modular references)
mkdir -p /tmp/cdxXY_gen
uv run datamodel-codegen \
  --input sbomify/apps/sboms/schemas/cdx_bom-X.Y.schema.json \
  --output /tmp/cdxXY_gen \
  --input-file-type jsonschema \
  --output-model-type pydantic_v2.BaseModel

# 3. Copy the generated __init__.py to the target file
cp /tmp/cdxXY_gen/__init__.py sbomify/apps/sboms/sbom_format_schemas/cyclonedx_X_Y.py

# 4. Update the header comment to reference the source URL
# Edit the file and change:
#   filename:  cdx_bom-X.Y.schema.json
# To:
#   filename:  https://raw.githubusercontent.com/CycloneDX/specification/refs/heads/master/schema/bom-X.Y.schema.json

# 5. Add alias for consistent naming (if needed)
# CycloneDX 1.7+ uses "CyclonedxBillOfMaterialsStandard" instead of "CyclonedxSoftwareBillOfMaterialsStandard"
# Add at the end of the file:
#   CyclonedxSoftwareBillOfMaterialsStandard = CyclonedxBillOfMaterialsStandard
```

### SPDX Schemas

To generate or update an SPDX schema:

```bash
# 1. Download the JSON schema
curl -o sbomify/apps/sboms/schemas/spdx_X.Y-schema.json \
  https://raw.githubusercontent.com/spdx/spdx-spec/vX.Y/schemas/spdx-schema.json

# 2. Generate the Pydantic model
uv run datamodel-codegen \
  --input sbomify/apps/sboms/schemas/spdx_X.Y-schema.json \
  --output sbomify/apps/sboms/sbom_format_schemas/spdx_X_Y.py \
  --input-file-type jsonschema \
  --output-model-type pydantic_v2.BaseModel
```

### SPDX 3.0 Schema

SPDX 3.0 uses JSON-LD with a graph-based structure (`@context` + `@graph`), which is incompatible with `datamodel-codegen`. The models in `spdx_3_0.py` are **hand-written** to cover the key types needed for upload validation, metadata extraction, and aggregated SBOM generation. Each model class includes a reference to the corresponding section in the SPDX 3.0.1 specification.

**Document structure:**

```json
{
  "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
  "@graph": [
    { "@id": "_:creationInfo", "type": "CreationInfo", "specVersion": "3.0.1", ... },
    { "type": "Organization", "spdxId": "urn:spdx:org-...", "creationInfo": "_:creationInfo", ... },
    { "type": "software_Package", "spdxId": "urn:spdx:pkg-...", "creationInfo": "_:creationInfo", ... },
    { "type": "SpdxDocument", "spdxId": "urn:spdx:doc-...", "element": ["urn:spdx:pkg-..."], ... }
  ]
}
```

Key differences from SPDX 2.x:
- **No root-level `spdxVersion`** — version comes from `CreationInfo.specVersion` inside the graph
- **`@context`** points to the JSON-LD context URL
- **`@graph`** is an array of all elements (packages, relationships, the document itself, etc.)
- **`SpdxDocument`** is an element inside `@graph`, not the root object
- **`CreationInfo`** is typically a blank node (`@id: "_:creationInfo"`) referenced by string from other elements
- **`element`** (singular) on SpdxDocument lists spdxId strings of contained elements

For backward compatibility, the parser also accepts a legacy format with `spdxVersion`/`elements` at the root level and normalizes it to the graph structure internally.

Reference: <https://spdx.github.io/spdx-spec/v3.0.1/>

## Adding Support for New Versions

After generating the schema file, you need to register it in the application:

### For CycloneDX

1. **Import the module** in `sbomify/apps/sboms/schemas.py`:

   ```python
   from .sbom_format_schemas import cyclonedx_X_Y as cdxXY
   ```

2. **Add to the enum** in `schemas.py`:

   ```python
   class CycloneDXSupportedVersion(str, Enum):
       v1_5 = "1.5"
       v1_6 = "1.6"
       v1_7 = "1.7"
       vX_Y = "X.Y"  # Add this
   ```

3. **Add to the module map** in `get_cyclonedx_module()`:

   ```python
   module_map: dict[CycloneDXSupportedVersion, ModuleType] = {
       CycloneDXSupportedVersion.v1_5: cdx15,
       CycloneDXSupportedVersion.v1_6: cdx16,
       CycloneDXSupportedVersion.v1_7: cdx17,
       CycloneDXSupportedVersion.vX_Y: cdxXY,  # Add this
   }
   ```

4. **Update type hints** in `validate_cyclonedx_sbom()` return type to include the new version.

5. **Add tests** in `sbomify/apps/sboms/tests/test_apis.py` to verify:
   - The new version is accepted
   - Version-specific features work correctly
   - Previous versions reject new-version-only fields

### For SPDX

1. **Add to the enum** in `schemas.py`:

   ```python
   class SPDXSupportedVersion(str, Enum):
       v2_2 = "2.2"
       v2_3 = "2.3"
       vX_Y = "X.Y"  # Add this
   ```

2. **Update `validate_spdx_sbom()`** if the new version requires different schema handling (e.g., SPDX 3.0 has a completely different structure).

3. **Add tests** to verify the new version works correctly.

## Current Supported Versions

- **CycloneDX:** 1.3, 1.4, 1.5, 1.6, 1.7
- **SPDX:** 2.2, 2.3, 3.0

## Schema Sources

- **CycloneDX:** <https://github.com/CycloneDX/specification>
- **SPDX:** <https://github.com/spdx/spdx-spec>

## Known Issues and Manual Patches

### CycloneDX 1.5: RefLinkType Bug

**Problem:** The `datamodel-codegen` tool incorrectly generates the `RefLinkType` class as an empty `BaseModel` when processing the CycloneDX 1.5 JSON schema. This is due to a bug in how it handles `"allOf": [{"$ref": ...}]` constructs.

The CycloneDX 1.5 schema defines:

```json
"refLinkType": {
  "allOf": [{"$ref": "#/definitions/refType"}]
}
```

This should translate to a string type (since `refType` is a string), but `datamodel-codegen` produces:

```python
class RefLinkType(BaseModel):
    pass  # Empty class - WRONG
```

**Impact:** Valid CycloneDX 1.5 SBOMs with string values in `dependencies[].ref` and `dependencies[].dependsOn[]` fail validation with errors like:

```text
Input should be a valid dictionary or instance of RefLinkType
```

**Fix Applied:** The `cyclonedx_1_5.py` file has been manually patched to change `RefLinkType` from an empty `BaseModel` to `RootModel[RefType]`, matching the correct behavior in CycloneDX 1.6.

**If Regenerating:** After regenerating `cyclonedx_1_5.py`, you must reapply this patch:

```python
# Change this:
class RefLinkType(BaseModel):
    """..."""

# To this:
class RefLinkType(RootModel[RefType]):
    """..."""
    root: RefType
```

## Notes

- The generated files are large (100-200KB) and should not be manually edited (except for known issues documented above)
- CycloneDX 1.7 changed the main class name from `CyclonedxSoftwareBillOfMaterialsStandard` to `CyclonedxBillOfMaterialsStandard` (removed "Software")
- We add an alias for backward compatibility in naming
- SPDX 2.x versions all use the same schema structure
- SPDX 3.0 uses a JSON-LD graph structure (`@context` + `@graph`); hand-written Pydantic models in `spdx_3_0.py` cover the key types (SPDX3Document, SoftwarePackage, Relationship, CreationInfo, Organization, Tool, Person, SoftwareAgent, Hash, ExternalRef, ExternalIdentifier)

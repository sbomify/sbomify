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

- **CycloneDX:** 1.5, 1.6, 1.7
- **SPDX:** 2.2, 2.3

## Schema Sources

- **CycloneDX:** <https://github.com/CycloneDX/specification>
- **SPDX:** <https://github.com/spdx/spdx-spec>

## Notes

- The generated files are large (100-200KB) and should not be manually edited
- CycloneDX 1.7 changed the main class name from `CyclonedxSoftwareBillOfMaterialsStandard` to `CyclonedxBillOfMaterialsStandard` (removed "Software")
- We add an alias for backward compatibility in naming
- SPDX 2.x versions all use the same schema structure, but SPDX 3.0 will require a different approach

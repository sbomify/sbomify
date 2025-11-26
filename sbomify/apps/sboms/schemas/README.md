# SBOM Schema Files

This directory contains JSON schema files for various SBOM formats that are used to validate uploaded SBOMs.

## CycloneDX Schemas

The CycloneDX schemas are official schema files from the [CycloneDX specification](https://github.com/CycloneDX/specification).

### Available Versions

- `cdx_bom-1.5.schema.json` - CycloneDX 1.5 specification
- `cdx_bom-1.6.schema.json` - CycloneDX 1.6 specification
- `cdx_bom-1.7.schema.json` - CycloneDX 1.7 specification

### Generating Pydantic Models

The JSON schemas are used to generate Pydantic models for validation. These models are stored in `sbomify/apps/sboms/sbom_format_schemas/`.

To generate a new Pydantic model from a CycloneDX schema:

```bash
# Use Python 3.11 to avoid compatibility issues with datamodel-code-generator
# The tool needs to generate to a directory (not a file) due to modular references

# Create a temporary directory for generation
mkdir -p /tmp/cdx_gen

# Generate the models
uv run --python 3.11 datamodel-codegen \
  --input sbomify/apps/sboms/schemas/cdx_bom-1.X.schema.json \
  --output /tmp/cdx_gen \
  --input-file-type jsonschema \
  --output-model-type pydantic_v2.BaseModel \
  --use-annotated \
  --use-standard-collections \
  --use-union-operator \
  --field-constraints \
  --snake-case-field \
  --target-python-version 3.10

# Copy the main file to the correct location
cp /tmp/cdx_gen/__init__.py sbomify/apps/sboms/sbom_format_schemas/cyclonedx_1_X.py

# Clean up
rm -rf /tmp/cdx_gen
```

Replace `X` with the version number (e.g., `7` for version 1.7).

### Important Notes

1. **Python Version**: Use Python 3.11 for generation due to compatibility issues with datamodel-code-generator and Python 3.14+
2. **Output Directory**: The tool requires an output directory (not a file) because CycloneDX schemas have modular references
3. **Main File**: The generated main file is `__init__.py` which should be renamed to `cyclonedx_1_X.py`
4. **Field Naming**: Version 1.7 uses snake_case field names (e.g., `spec_version`) with camelCase aliases (e.g., `specVersion`)
5. **Class Names**:
   - Versions 1.5 and 1.6: `CyclonedxSoftwareBillOfMaterialsStandard`
   - Version 1.7: `CyclonedxBillOfMaterialsStandard`

### After Generating a New Version

After generating a new schema version, you need to update the following files:

1. **`sbomify/apps/sboms/versioning.py`**
   - Add the new version to `CycloneDXSupportedVersion` enum

2. **`sbomify/apps/sboms/schemas.py`**
   - Import the new module (e.g., `from .sbom_format_schemas import cyclonedx_1_7 as cdx17`)
   - Add to `CycloneDXSupportedVersion` enum
   - Add to `get_cyclonedx_module()` function

3. **`sbomify/apps/sboms/cyclonedx_validator.py`**
   - Import the new module
   - Add to `_version_map` in `__init__`
   - Add to `supported_versions` list in `_validate_version()`

4. **`sbomify/apps/sboms/apis.py`**
   - Import the new module
   - Add validation case in `sbom_upload_cyclonedx()`

5. **`sbomify/apps/sboms/utils.py`**
   - Import the new module
   - Add to `get_cyclonedx_module()` function

6. **`sbomify/apps/sboms/tests/test_cyclonedx_validator.py`**
   - Add test cases for the new version

### Running Tests

After adding support for a new version, run the tests:

```bash
# Run CycloneDX validator tests
uv run --python 3.11 pytest sbomify/apps/sboms/tests/test_cyclonedx_validator.py -v

# Run all SBOM tests
uv run --python 3.11 pytest sbomify/apps/sboms/tests/ -v
```

### Linting

After making changes, run linting and formatting:

```bash
uv run --python 3.11 ruff check sbomify/apps/sboms/ --fix
uv run --python 3.11 ruff format sbomify/apps/sboms/
```

## SPDX Schemas

The SPDX schemas are official schema files from the [SPDX specification](https://github.com/spdx/spdx-spec).

### Supported SPDX Versions

- `spdx_2.3-schema.json` - SPDX 2.3 specification
- `spdx_2.3.1-schema.json` - SPDX 2.3.1 specification

SPDX schemas are processed differently than CycloneDX schemas and do not require separate Pydantic model generation.

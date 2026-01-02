import pytest

from sbomify.apps.sboms.cyclonedx_validator import (
    CycloneDXValidator,
    SBOMSchemaError,
    SBOMVersionError,
)


def test_validate_valid_1_3_sbom(sample_cyclonedx_schema_dict):
    """Test validation of a valid CycloneDX 1.3 SBOM."""
    sbom_data = sample_cyclonedx_schema_dict.copy()
    sbom_data["specVersion"] = "1.3"
    validated_sbom = CycloneDXValidator("1.3").validate(sbom_data)
    assert validated_sbom.specVersion == "1.3"
    # bomFormat is an enum in 1.3
    assert validated_sbom.bomFormat.value == "CycloneDX"


def test_validate_valid_1_4_sbom(sample_cyclonedx_schema_dict):
    """Test validation of a valid CycloneDX 1.4 SBOM."""
    sbom_data = sample_cyclonedx_schema_dict.copy()
    sbom_data["specVersion"] = "1.4"
    validated_sbom = CycloneDXValidator("1.4").validate(sbom_data)
    assert validated_sbom.specVersion == "1.4"
    # bomFormat is an enum in 1.4
    assert validated_sbom.bomFormat.value == "CycloneDX"


def test_validate_valid_1_5_sbom(sample_cyclonedx_schema_dict):
    """Test validation of a valid CycloneDX 1.5 SBOM."""
    sbom_data = sample_cyclonedx_schema_dict.copy()
    sbom_data["specVersion"] = "1.5"
    validated_sbom = CycloneDXValidator("1.5").validate(sbom_data)
    assert validated_sbom.specVersion == "1.5"
    assert validated_sbom.bomFormat == "CycloneDX"


def test_validate_valid_1_6_sbom(sample_cyclonedx_schema_dict):
    """Test validation of a valid CycloneDX 1.6 SBOM."""
    sbom_data = sample_cyclonedx_schema_dict.copy()
    sbom_data["specVersion"] = "1.6"
    validated_sbom = CycloneDXValidator("1.6").validate(sbom_data)
    assert validated_sbom.specVersion == "1.6"
    assert validated_sbom.bomFormat == "CycloneDX"


def test_validate_invalid_version():
    """Test validation with an invalid version."""
    with pytest.raises(SBOMVersionError):
        CycloneDXValidator("1.2")


def test_validate_unsupported_version():
    """Test validation with unsupported version."""
    with pytest.raises(SBOMVersionError):
        CycloneDXValidator("1.0")


def test_validate_invalid_format():
    """Test validation with invalid bomFormat."""
    with pytest.raises(SBOMSchemaError) as exc_info:
        CycloneDXValidator("1.5").validate({"specVersion": "1.5", "bomFormat": "Invalid"})
    assert "schema validation failed" in str(exc_info.value).lower()


def test_get_version_specific_fields_1_3():
    """Test getting version-specific fields for 1.3."""
    validator = CycloneDXValidator("1.3")
    fields = validator.get_version_specific_fields()
    assert "required" in fields
    assert "optional" in fields
    assert "bomFormat" in fields["required"]
    assert "specVersion" in fields["required"]


def test_get_version_specific_fields_1_4():
    """Test getting version-specific fields for 1.4."""
    validator = CycloneDXValidator("1.4")
    fields = validator.get_version_specific_fields()
    assert "required" in fields
    assert "optional" in fields
    assert "bomFormat" in fields["required"]
    assert "specVersion" in fields["required"]


def test_get_version_specific_fields_1_5():
    """Test getting version-specific fields for 1.5."""
    validator = CycloneDXValidator("1.5")
    fields = validator.get_version_specific_fields()
    assert "required" in fields
    assert "optional" in fields
    assert "bomFormat" in fields["required"]
    assert "metadata" in fields["required"]


def test_get_version_specific_fields_1_6():
    """Test getting version-specific fields for 1.6."""
    validator = CycloneDXValidator("1.6")
    fields = validator.get_version_specific_fields()
    assert "required" in fields
    assert "optional" in fields
    assert "bomFormat" in fields["required"]
    assert "metadata" in fields["required"]


def test_validate_version_specific_requirements_1_5():
    """Test version-specific requirements validation for 1.5."""
    validator = CycloneDXValidator("1.5")
    data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {"component": {"name": "test"}},
    }
    # This should not raise any exception
    validator.validate_version_specific_requirements(data)


def test_validate_version_specific_requirements_1_6():
    """Test version-specific requirements validation for 1.6."""
    validator = CycloneDXValidator("1.6")
    data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {"component": {"name": "test"}},
    }
    # This should not raise any exception
    validator.validate_version_specific_requirements(data)


def test_validate_version_specific_requirements_missing_required():
    """Test validation with missing required fields."""
    validator = CycloneDXValidator("1.5")
    data = {"specVersion": "1.5"}  # Missing bomFormat
    with pytest.raises(SBOMSchemaError) as exc_info:
        validator.validate_version_specific_requirements(data)
    assert "Missing required field: bomFormat" in str(exc_info.value)


def test_validate_version_specific_requirements_invalid_format():
    """Test validation with invalid bomFormat."""
    validator = CycloneDXValidator("1.5")
    data = {
        "bomFormat": "Invalid",
        "specVersion": "1.5",
        "metadata": {"component": {"name": "test"}},
    }
    with pytest.raises(SBOMSchemaError) as exc_info:
        validator.validate_version_specific_requirements(data)
    assert "Invalid bomFormat: expected 'CycloneDX', got Invalid" in str(exc_info.value)


def test_validate_version_specific_requirements_version_mismatch():
    """Test validation with version mismatch."""
    validator = CycloneDXValidator("1.5")
    data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",  # Mismatch with requested version
        "metadata": {"component": {"name": "test"}},
    }
    with pytest.raises(SBOMSchemaError) as exc_info:
        validator.validate_version_specific_requirements(data)
    assert "CycloneDX version mismatch: expected 1.5, got 1.6" in str(exc_info.value)


def test_validate_1_5_sbom_with_dependencies():
    """Test that CycloneDX 1.5 correctly handles dependencies with string refs.

    This is a regression test for a bug where datamodel-codegen generated
    RefLinkType as an empty BaseModel instead of RootModel[RefType], causing
    valid SBOMs with string dependency refs to fail validation.

    See: sbomify/apps/sboms/sbom_format_schemas/README.md for details.
    """
    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "bom-ref": "main-component",
                "type": "application",
                "name": "test-app",
                "version": "1.0.0",
            }
        },
        "components": [
            {
                "bom-ref": "pkg:maven/org.example/lib-a@1.0.0",
                "type": "library",
                "name": "lib-a",
                "version": "1.0.0",
                "purl": "pkg:maven/org.example/lib-a@1.0.0",
            },
            {
                "bom-ref": "pkg:maven/org.example/lib-b@2.0.0",
                "type": "library",
                "name": "lib-b",
                "version": "2.0.0",
                "purl": "pkg:maven/org.example/lib-b@2.0.0",
            },
        ],
        "dependencies": [
            {"ref": "main-component", "dependsOn": ["pkg:maven/org.example/lib-a@1.0.0"]},
            {
                "ref": "pkg:maven/org.example/lib-a@1.0.0",
                "dependsOn": ["pkg:maven/org.example/lib-b@2.0.0"],
            },
            {"ref": "pkg:maven/org.example/lib-b@2.0.0"},
        ],
    }

    # This should not raise - string refs should be accepted
    validated_sbom = CycloneDXValidator("1.5").validate(sbom_data)

    assert validated_sbom.specVersion == "1.5"
    assert len(validated_sbom.dependencies) == 3

    # Verify the dependency refs are correctly parsed
    dep_refs = [str(dep.ref.root.root) for dep in validated_sbom.dependencies]
    assert "main-component" in dep_refs
    assert "pkg:maven/org.example/lib-a@1.0.0" in dep_refs
    assert "pkg:maven/org.example/lib-b@2.0.0" in dep_refs

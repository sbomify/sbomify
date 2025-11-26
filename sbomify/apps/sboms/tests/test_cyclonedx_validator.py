import pytest

from sbomify.apps.sboms.cyclonedx_validator import (
    CycloneDXValidator,
    SBOMSchemaError,
    SBOMVersionError,
)


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


def test_validate_valid_1_7_sbom(sample_cyclonedx_schema_dict):
    """Test validation of a valid CycloneDX 1.7 SBOM."""
    sbom_data = sample_cyclonedx_schema_dict.copy()
    sbom_data["specVersion"] = "1.7"
    validated_sbom = CycloneDXValidator("1.7").validate(sbom_data)
    assert validated_sbom.spec_version == "1.7"
    assert validated_sbom.bom_format.value == "CycloneDX"


def test_validate_invalid_version():
    """Test validation with an invalid version."""
    with pytest.raises(SBOMVersionError):
        CycloneDXValidator("1.4")


def test_validate_missing_version():
    """Test validation with missing version."""
    with pytest.raises(SBOMVersionError):
        CycloneDXValidator("1.4")


def test_validate_invalid_format():
    """Test validation with invalid bomFormat."""
    with pytest.raises(SBOMSchemaError) as exc_info:
        CycloneDXValidator("1.5").validate({"specVersion": "1.5", "bomFormat": "Invalid"})
    assert "schema validation failed" in str(exc_info.value).lower()


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


def test_get_version_specific_fields_1_7():
    """Test getting version-specific fields for 1.7."""
    validator = CycloneDXValidator("1.7")
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


def test_validate_version_specific_requirements_1_7():
    """Test version-specific requirements validation for 1.7."""
    validator = CycloneDXValidator("1.7")
    data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
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

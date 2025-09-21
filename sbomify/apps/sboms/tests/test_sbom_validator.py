import pytest
from typing import Any

from sbomify.apps.sboms.sbom_base_validator import SBOMValidator, SBOMVersionError, SBOMSchemaError
from sbomify.apps.sboms.sbom_validator import SPDXValidator, get_validator
from sbomify.apps.sboms.schemas import SBOMFormat


def test_get_validator_cyclonedx() -> None:
    """Test getting CycloneDX validator."""
    # Arrange & Act
    validator = get_validator(SBOMFormat.cyclonedx, "1.6")

    # Assert
    assert isinstance(validator, SBOMValidator)
    assert validator.version == "1.6"


def test_get_validator_spdx() -> None:
    """Test getting SPDX validator."""
    # Arrange & Act
    validator = get_validator(SBOMFormat.spdx, "2.3")

    # Assert
    assert isinstance(validator, SBOMValidator)
    assert validator.version == "2.3"


def test_get_validator_invalid_format() -> None:
    """Test getting validator with invalid format raises ValueError."""
    # Arrange & Act & Assert
    with pytest.raises(ValueError, match="Unsupported SBOM format"):
        get_validator("invalid", "1.0")


def test_spdx_validator_version() -> None:
    """Test SPDX validator version handling."""
    # Arrange & Act
    validator = SPDXValidator("2.3")

    # Assert
    assert validator.version == "2.3"


def test_spdx_validator_invalid_version() -> None:
    """Test SPDX validator raises error for invalid version."""
    # Arrange & Act & Assert
    with pytest.raises(SBOMVersionError, match="Unsupported SPDX version: 1.0"):
        SPDXValidator("1.0")


def test_spdx_validator_fields() -> None:
    """Test SPDX validator field handling."""
    # Arrange
    validator = SPDXValidator("2.3")

    # Act
    fields = validator.get_version_specific_fields()

    # Assert
    # Check required fields
    assert "SPDXID" in fields["required"]
    assert "creationInfo" in fields["required"]
    assert "dataLicense" in fields["required"]
    assert "name" in fields["required"]
    assert "spdxVersion" in fields["required"]
    assert "documentNamespace" in fields["required"]  # 2.3 specific

    # Check optional fields
    assert "packages" in fields["optional"]
    assert "relationships" in fields["optional"]
    assert "snippets" in fields["optional"]  # 2.3 specific


def test_spdx_validator_validation() -> None:
    """Test SPDX validator validation with valid data."""
    # Arrange
    validator = SPDXValidator("2.3")
    valid_data: dict[str, Any] = {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {},
        "dataLicense": "CC0-1.0",
        "name": "test",
        "spdxVersion": "SPDX-2.3",
        "documentNamespace": "https://example.com/ns",
    }

    # Act
    validated = validator.validate(valid_data)

    # Assert
    assert validated.name == "test"


def test_spdx_validator_version_mismatch() -> None:
    """Test SPDX validator raises error for version mismatch."""
    # Arrange
    validator = SPDXValidator("2.3")
    invalid_version = {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {},
        "dataLicense": "CC0-1.0",
        "name": "test",
        "spdxVersion": "SPDX-2.2",
        "documentNamespace": "https://example.com/ns",
    }

    # Act & Assert
    with pytest.raises(SBOMSchemaError, match="SPDX version mismatch: expected SPDX-2.3, got SPDX-2.2"):
        validator.validate_version_specific_requirements(invalid_version)


def test_spdx_validator_missing_required_field() -> None:
    """Test SPDX validator raises error for missing required field (schema-driven)."""
    validator = SPDXValidator("2.3")
    missing_field = {
        # "SPDXID" is missing
        "creationInfo": {},
        "dataLicense": "CC0-1.0",
        "name": "test",
        "spdxVersion": "SPDX-2.3",
        "documentNamespace": "https://example.com/ns",
    }
    with pytest.raises(SBOMSchemaError) as exc_info:
        validator.validate(missing_field)
    msg = str(exc_info.value)
    assert "SPDX schema validation failed" in msg
    assert "SPDXID" in msg
    assert "Field required" in msg


def test_spdx_validator_invalid_schema() -> None:
    """Test SPDX validator raises error for invalid schema (schema-driven)."""
    validator = SPDXValidator("2.3")
    invalid_schema = {"invalid": "data", "spdxVersion": "SPDX-2.3"}
    with pytest.raises(SBOMSchemaError) as exc_info:
        validator.validate(invalid_schema)
    msg = str(exc_info.value)
    assert "SPDX schema validation failed" in msg
    assert "Field required" in msg
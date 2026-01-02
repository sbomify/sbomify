import json
from pathlib import Path

import pytest

from sbomify.apps.sboms.versioning import CycloneDXSupportedVersion

from ..schemas import (
    CustomLicenseSchema,
    SPDXPackage,
    SPDXSchema,
    get_cyclonedx_module,
    validate_cyclonedx_sbom,
)

TEST_DATA_DIR = Path(__file__).parent / "test_data"


@pytest.fixture
def sample_spdx_package_dict():
    return dict(
        name="test",
        versionInfo="1.0",
        licenseConcluded="GPL-3.0",
        licenseDeclared="MIT",
        externalRefs=[{"referenceType": "purl", "referenceLocator": "pkg:test@1.0"}],
    )


@pytest.fixture
def sample_spdx_schema_dict(sample_spdx_package_dict):  # noqa: F811
    return dict(
        SPDXID="SPDXRef-DOCUMENT",
        creationInfo={},
        dataLicense="CC0-1.0",
        name="test",
        spdxVersion="SPDX-2.2",
        packages=[sample_spdx_package_dict],
    )


@pytest.fixture
def sample_cyclonedx_component_dict():
    return {
        "bom-ref": "urn:uuid:9d7b8a1b-7e1c-4c8e-bd9d-dee9b6f6f7f3",
        "name": "test",
        "type": "library",
        "version": "1.0",
        "purl": "pkg:test@1.0",
    }


@pytest.fixture
def sample_cyclonedx_schema_dict(sample_cyclonedx_component_dict):  # noqa: F811
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:9d7b8a1b-7e1c-4c8e-bd9d-dee9b6f6f7f3",
        "version": 1,
        "metadata": {
            "component": {
                "bom-ref": "aabbccddeeffgg",
                "type": "library",
                "name": "test",
                "version": "1.0",
            }
        },
        "components": [sample_cyclonedx_component_dict],
    }


def test_spdx_package(sample_spdx_package_dict):  # noqa: F811
    spdx_package = SPDXPackage(**sample_spdx_package_dict)

    assert spdx_package.name == "test"
    assert spdx_package.license == "MIT"
    assert spdx_package.version == "1.0"
    assert spdx_package.purl == "pkg:test@1.0"


def test_spdx_schema(sample_spdx_schema_dict):  # noqa: F811
    spdx_schema = SPDXSchema(**sample_spdx_schema_dict)

    assert spdx_schema.name == "test"
    assert spdx_schema.packages[0].purl == "pkg:test@1.0"


def test_get_cyclonedx_module():
    """Test that get_cyclonedx_module returns correct modules for all versions."""
    base = "sbomify.apps.sboms.sbom_format_schemas"
    assert get_cyclonedx_module(CycloneDXSupportedVersion.v1_3).__name__ == f"{base}.cyclonedx_1_3"
    assert get_cyclonedx_module(CycloneDXSupportedVersion.v1_4).__name__ == f"{base}.cyclonedx_1_4"
    assert get_cyclonedx_module(CycloneDXSupportedVersion.v1_5).__name__ == f"{base}.cyclonedx_1_5"
    assert get_cyclonedx_module(CycloneDXSupportedVersion.v1_6).__name__ == f"{base}.cyclonedx_1_6"
    assert get_cyclonedx_module(CycloneDXSupportedVersion.v1_7).__name__ == f"{base}.cyclonedx_1_7"


def test_custom_license():
    custom_license = CustomLicenseSchema(name="Test License", url="https://example.com", text="Test License Text")

    assert custom_license.name == "Test License"
    assert custom_license.url == "https://example.com"
    assert custom_license.text == "Test License Text"

    license_1_5 = custom_license.to_cyclonedx(CycloneDXSupportedVersion.v1_5)
    license_1_6 = custom_license.to_cyclonedx(CycloneDXSupportedVersion.v1_6)

    cdx15 = get_cyclonedx_module(CycloneDXSupportedVersion.v1_5)
    cdx16 = get_cyclonedx_module(CycloneDXSupportedVersion.v1_6)

    assert license_1_5.name == "Test License"
    assert license_1_5.url == "https://example.com"
    assert isinstance(license_1_5.text, cdx15.Attachment)
    assert license_1_5.text.content == "Test License Text"
    assert hasattr(license_1_5, "acknowledgement") is False

    assert license_1_6.name == "Test License"
    assert license_1_6.url == "https://example.com"
    assert isinstance(license_1_6.text, cdx16.Attachment)
    assert license_1_6.text.content == "Test License Text"
    assert hasattr(license_1_6, "acknowledgement") is True


def test_custom_license_1_3_and_1_4():
    """Test CustomLicenseSchema.to_cyclonedx for 1.3 and 1.4 which use License2 for name-based licenses."""
    custom_license = CustomLicenseSchema(name="Test License", url="https://example.com", text="Test License Text")

    cdx13 = get_cyclonedx_module(CycloneDXSupportedVersion.v1_3)
    cdx14 = get_cyclonedx_module(CycloneDXSupportedVersion.v1_4)

    license_1_3 = custom_license.to_cyclonedx(CycloneDXSupportedVersion.v1_3)
    license_1_4 = custom_license.to_cyclonedx(CycloneDXSupportedVersion.v1_4)

    # 1.3/1.4 use License2 for name-based licenses (License1 is for ID-based)
    assert isinstance(license_1_3, cdx13.License2)
    assert license_1_3.name == "Test License"
    assert license_1_3.url == "https://example.com"
    assert isinstance(license_1_3.text, cdx13.Attachment)
    assert license_1_3.text.content == "Test License Text"
    # No acknowledgement field in 1.3
    assert not hasattr(license_1_3, "acknowledgement") or license_1_3.acknowledgement is None

    # 1.4 also uses License2 for name-based licenses
    assert isinstance(license_1_4, cdx14.License2)
    assert license_1_4.name == "Test License"
    assert license_1_4.url == "https://example.com"
    assert isinstance(license_1_4.text, cdx14.Attachment)
    assert license_1_4.text.content == "Test License Text"
    # No acknowledgement field in 1.4
    assert not hasattr(license_1_4, "acknowledgement") or license_1_4.acknowledgement is None


def test_validate_cyclonedx_sbom_1_3():
    """Test validate_cyclonedx_sbom for version 1.3."""
    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.3",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "test-app",
                "version": "1.0.0",
            }
        },
    }
    payload, version = validate_cyclonedx_sbom(sbom_data)
    assert version == "1.3"
    assert payload.specVersion == "1.3"
    assert payload.metadata.component.name == "test-app"


def test_validate_cyclonedx_sbom_1_4():
    """Test validate_cyclonedx_sbom for version 1.4."""
    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.4",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "test-app-14",
                "version": "2.0.0",
            }
        },
    }
    payload, version = validate_cyclonedx_sbom(sbom_data)
    assert version == "1.4"
    assert payload.specVersion == "1.4"
    assert payload.metadata.component.name == "test-app-14"


def test_validate_cyclonedx_sbom_unsupported_version():
    """Test validate_cyclonedx_sbom raises error for unsupported version."""
    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.2",
        "version": 1,
    }
    with pytest.raises(ValueError) as exc_info:
        validate_cyclonedx_sbom(sbom_data)
    assert "Unsupported CycloneDX specVersion: 1.2" in str(exc_info.value)


@pytest.fixture
def dependencytrack_frontend_sbom():
    """Real-world CycloneDX 1.3 SBOM from DependencyTrack frontend.

    Source: https://github.com/DependencyTrack/frontend/releases/download/4.13.6/bom.json
    """
    sbom_path = TEST_DATA_DIR / "dependencytrack_frontend.cdx.1.3.json"
    with open(sbom_path) as f:
        return json.load(f)


def test_validate_cyclonedx_1_3_real_world_sbom(dependencytrack_frontend_sbom):
    """Test validation with real-world DependencyTrack frontend CycloneDX 1.3 SBOM.

    Source: https://github.com/DependencyTrack/frontend/releases/download/4.13.6/bom.json
    """
    payload, version = validate_cyclonedx_sbom(dependencytrack_frontend_sbom)

    assert version == "1.3"
    assert payload.specVersion == "1.3"
    assert payload.bomFormat.value == "CycloneDX"
    assert payload.serialNumber == "urn:uuid:e43bc4c7-dc6b-4a24-a595-e4a5177e16ba"
    assert payload.version == 1

    # Verify metadata
    assert payload.metadata is not None
    assert payload.metadata.timestamp is not None
    assert payload.metadata.component.name == "frontend"
    assert payload.metadata.component.version == "4.13.6"
    assert payload.metadata.component.group == "@dependencytrack"
    assert payload.metadata.component.purl == "pkg:npm/%40dependencytrack/frontend@4.13.6"

    # Verify tools
    assert len(payload.metadata.tools) == 1
    assert payload.metadata.tools[0].name == "webpack-plugin"
    assert payload.metadata.tools[0].vendor == "CycloneDX"

    # Verify components exist
    assert payload.components is not None
    assert len(payload.components) > 0
    component_names = [c.name for c in payload.components]
    assert "core-js" in component_names
    assert "vue" in component_names

    # Verify dependencies exist
    assert payload.dependencies is not None
    assert len(payload.dependencies) > 0

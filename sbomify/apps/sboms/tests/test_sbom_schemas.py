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


class TestComponentMetadataToCycloneDX:
    """Integration tests for ComponentMetaData.to_cyclonedx() across all CycloneDX versions.

    These tests verify that generated SBOM metadata is schema-compliant for each
    supported CycloneDX version, with special attention to version-specific fields
    like manufacturer (1.6+) and PostalAddress (1.6+).
    """

    @pytest.fixture
    def component_metadata_with_manufacturer(self):
        """Create a ComponentMetaData with manufacturer, supplier, and authors.

        Note: Licenses are excluded here as CycloneDX 1.3/1.4 have different LicenseChoice
        schema structures that require version-specific handling outside this test scope.
        """
        from sbomify.apps.sboms.schemas import ComponentMetaData, SupplierSchema

        return ComponentMetaData(
            id="test-component-123",
            name="Test Component",
            supplier=SupplierSchema(
                name="Test Supplier Corp",
                url=["https://supplier.example.com"],
                address="100 Supplier Street, City, Country",
                contacts=[
                    {"name": "Supplier Contact", "email": "supplier@example.com", "phone": "+1-555-0100"}
                ],
            ),
            manufacturer=SupplierSchema(
                name="Test Manufacturer Inc",
                url=["https://manufacturer.example.com", "https://mfg-alt.example.com"],
                address="200 Factory Lane, Industrial City, Country",
                contacts=[
                    {"name": "Manufacturing Lead", "email": "mfg@example.com", "phone": "+1-555-0200"},
                    {"name": "Quality Contact", "email": "quality@example.com"},
                ],
            ),
            authors=[
                {"name": "Alice Author", "email": "alice@example.com", "phone": "+1-555-0300"},
                {"name": "Bob Builder", "email": "bob@example.com"},
            ],
            licenses=[],  # Empty to avoid version-specific LicenseChoice issues in 1.3/1.4
            lifecycle_phase="build",
        )

    @pytest.fixture
    def component_metadata_with_licenses(self):
        """Create a ComponentMetaData with licenses for versions 1.5+."""
        from sbomify.apps.sboms.schemas import ComponentMetaData, SupplierSchema

        return ComponentMetaData(
            id="test-component-123",
            name="Test Component",
            supplier=SupplierSchema(name="Test Supplier Corp"),
            manufacturer=SupplierSchema(name="Test Manufacturer Inc"),
            authors=[],
            licenses=["MIT", "Apache-2.0"],
            lifecycle_phase="build",
        )

    def test_cyclonedx_1_3_with_manufacture(self, component_metadata_with_manufacturer):
        """Test CycloneDX 1.3 - component manufacturer uses 'manufacture' field."""
        cdx_metadata = component_metadata_with_manufacturer.to_cyclonedx(CycloneDXSupportedVersion.v1_3)

        # Validate against schema
        cdx13 = get_cyclonedx_module(CycloneDXSupportedVersion.v1_3)
        assert isinstance(cdx_metadata, cdx13.Metadata)

        # 'manufacture' (component manufacturer) SHOULD be present in 1.3
        assert cdx_metadata.manufacture is not None
        assert cdx_metadata.manufacture.name == "Test Manufacturer Inc"
        assert cdx_metadata.manufacture.url == [
            "https://manufacturer.example.com",
            "https://mfg-alt.example.com",
        ]

        # supplier should be present
        assert cdx_metadata.supplier is not None
        assert cdx_metadata.supplier.name == "Test Supplier Corp"
        assert cdx_metadata.supplier.url == ["https://supplier.example.com"]

        # authors should be present
        assert cdx_metadata.authors is not None
        assert len(cdx_metadata.authors) == 2
        assert cdx_metadata.authors[0].name == "Alice Author"

        # Serialize and validate it can be deserialized
        serialized = cdx_metadata.model_dump(mode="json", exclude_none=True, by_alias=True)
        validated = cdx13.Metadata(**serialized)
        assert validated.supplier.name == "Test Supplier Corp"
        assert validated.manufacture.name == "Test Manufacturer Inc"

    def test_cyclonedx_1_4_with_manufacture(self, component_metadata_with_manufacturer):
        """Test CycloneDX 1.4 - component manufacturer uses 'manufacture' field."""
        cdx_metadata = component_metadata_with_manufacturer.to_cyclonedx(CycloneDXSupportedVersion.v1_4)

        cdx14 = get_cyclonedx_module(CycloneDXSupportedVersion.v1_4)
        assert isinstance(cdx_metadata, cdx14.Metadata)

        # 'manufacture' (component manufacturer) SHOULD be present in 1.4
        assert cdx_metadata.manufacture is not None
        assert cdx_metadata.manufacture.name == "Test Manufacturer Inc"

        # supplier should be present
        assert cdx_metadata.supplier is not None
        assert cdx_metadata.supplier.name == "Test Supplier Corp"

        # Serialize and validate
        serialized = cdx_metadata.model_dump(mode="json", exclude_none=True, by_alias=True)
        validated = cdx14.Metadata(**serialized)
        assert validated.supplier.name == "Test Supplier Corp"
        assert validated.manufacture.name == "Test Manufacturer Inc"

    def test_cyclonedx_1_5_with_manufacture(self, component_metadata_with_manufacturer):
        """Test CycloneDX 1.5 - component manufacturer uses 'manufacture' field, has lifecycles."""
        cdx_metadata = component_metadata_with_manufacturer.to_cyclonedx(CycloneDXSupportedVersion.v1_5)

        cdx15 = get_cyclonedx_module(CycloneDXSupportedVersion.v1_5)
        assert isinstance(cdx_metadata, cdx15.Metadata)

        # 'manufacture' (component manufacturer) SHOULD be present in 1.5
        assert cdx_metadata.manufacture is not None
        assert cdx_metadata.manufacture.name == "Test Manufacturer Inc"
        # Address should NOT be set in 1.5 (PostalAddress not available)
        assert not hasattr(cdx_metadata.manufacture, "address") or cdx_metadata.manufacture.address is None

        # supplier should be present (but no PostalAddress in 1.5)
        assert cdx_metadata.supplier is not None
        assert cdx_metadata.supplier.name == "Test Supplier Corp"
        assert not hasattr(cdx_metadata.supplier, "address") or cdx_metadata.supplier.address is None

        # lifecycles should be present (added in 1.5)
        assert cdx_metadata.lifecycles is not None
        assert len(cdx_metadata.lifecycles) == 1
        assert cdx_metadata.lifecycles[0].phase == "build"

        # Serialize and validate
        serialized = cdx_metadata.model_dump(mode="json", exclude_none=True, by_alias=True)
        validated = cdx15.Metadata(**serialized)
        assert validated.supplier.name == "Test Supplier Corp"
        assert validated.manufacture.name == "Test Manufacturer Inc"
        assert validated.lifecycles[0].phase == "build"

    def test_cyclonedx_1_6_with_manufacturer(self, component_metadata_with_manufacturer):
        """Test CycloneDX 1.6 - uses forward-looking 'manufacturer' field with PostalAddress."""
        cdx_metadata = component_metadata_with_manufacturer.to_cyclonedx(CycloneDXSupportedVersion.v1_6)

        cdx16 = get_cyclonedx_module(CycloneDXSupportedVersion.v1_6)
        assert isinstance(cdx_metadata, cdx16.Metadata)

        # 'manufacturer' SHOULD be present in 1.6 (forward-looking approach)
        assert cdx_metadata.manufacturer is not None
        assert cdx_metadata.manufacturer.name == "Test Manufacturer Inc"
        assert cdx_metadata.manufacturer.url == [
            "https://manufacturer.example.com",
            "https://mfg-alt.example.com",
        ]

        # PostalAddress should be used for manufacturer address in 1.6
        assert cdx_metadata.manufacturer.address is not None
        assert isinstance(cdx_metadata.manufacturer.address, cdx16.PostalAddress)
        assert cdx_metadata.manufacturer.address.streetAddress == "200 Factory Lane, Industrial City, Country"

        # manufacturer contacts should be present
        assert cdx_metadata.manufacturer.contact is not None
        assert len(cdx_metadata.manufacturer.contact) == 2
        assert cdx_metadata.manufacturer.contact[0].name == "Manufacturing Lead"
        assert cdx_metadata.manufacturer.contact[0].email == "mfg@example.com"
        assert cdx_metadata.manufacturer.contact[1].name == "Quality Contact"

        # supplier should also have PostalAddress in 1.6
        assert cdx_metadata.supplier is not None
        assert cdx_metadata.supplier.address is not None
        assert isinstance(cdx_metadata.supplier.address, cdx16.PostalAddress)
        assert cdx_metadata.supplier.address.streetAddress == "100 Supplier Street, City, Country"

        # metadata.manufacture (deprecated) should NOT be set
        assert cdx_metadata.manufacture is None

        # Serialize and validate - this is the key integration test
        serialized = cdx_metadata.model_dump(mode="json", exclude_none=True, by_alias=True)

        # Validate the serialized output can be parsed by the schema
        validated = cdx16.Metadata(**serialized)
        assert validated.manufacturer.name == "Test Manufacturer Inc"
        assert validated.manufacturer.address.streetAddress == "200 Factory Lane, Industrial City, Country"
        assert validated.supplier.name == "Test Supplier Corp"
        assert validated.lifecycles[0].phase == "build"

    def test_cyclonedx_1_7_with_manufacturer(self, component_metadata_with_manufacturer):
        """Test CycloneDX 1.7 - uses forward-looking 'manufacturer' field with PostalAddress."""
        cdx_metadata = component_metadata_with_manufacturer.to_cyclonedx(CycloneDXSupportedVersion.v1_7)

        cdx17 = get_cyclonedx_module(CycloneDXSupportedVersion.v1_7)
        assert isinstance(cdx_metadata, cdx17.Metadata)

        # 'manufacturer' SHOULD be present in 1.7 (forward-looking approach)
        assert cdx_metadata.manufacturer is not None
        assert cdx_metadata.manufacturer.name == "Test Manufacturer Inc"
        assert cdx_metadata.manufacturer.url == [
            "https://manufacturer.example.com",
            "https://mfg-alt.example.com",
        ]

        # PostalAddress should be used for manufacturer address in 1.7
        assert cdx_metadata.manufacturer.address is not None
        assert isinstance(cdx_metadata.manufacturer.address, cdx17.PostalAddress)
        assert cdx_metadata.manufacturer.address.streetAddress == "200 Factory Lane, Industrial City, Country"

        # metadata.manufacture (deprecated) should NOT be set
        assert cdx_metadata.manufacture is None

        # Serialize and validate
        serialized = cdx_metadata.model_dump(mode="json", exclude_none=True, by_alias=True)
        validated = cdx17.Metadata(**serialized)
        assert validated.manufacturer.name == "Test Manufacturer Inc"
        assert validated.supplier.name == "Test Supplier Corp"

    def test_full_sbom_with_manufacturer_1_6(self, component_metadata_with_manufacturer):
        """Test generating a complete CycloneDX 1.6 SBOM with manufacturer and validating against schema."""
        cdx16 = get_cyclonedx_module(CycloneDXSupportedVersion.v1_6)

        # Generate metadata
        cdx_metadata = component_metadata_with_manufacturer.to_cyclonedx(CycloneDXSupportedVersion.v1_6)

        # Add a component to the metadata
        cdx_metadata.component = cdx16.Component(
            name="Test Application",
            type=cdx16.Type.application,
            version="1.0.0",
        )

        # Create a full SBOM
        sbom = cdx16.CyclonedxSoftwareBillOfMaterialsStandard(
            bomFormat="CycloneDX",
            specVersion="1.6",
            serialNumber="urn:uuid:12345678-1234-1234-1234-123456789012",
            version=1,
            metadata=cdx_metadata,
            components=[
                cdx16.Component(
                    name="dependency-lib",
                    type=cdx16.Type.library,
                    version="2.0.0",
                )
            ],
        )

        # Serialize to JSON
        sbom_json = sbom.model_dump(mode="json", exclude_none=True, by_alias=True)

        # Validate the full SBOM can be parsed
        validated_sbom = cdx16.CyclonedxSoftwareBillOfMaterialsStandard(**sbom_json)

        assert validated_sbom.specVersion == "1.6"
        assert validated_sbom.bomFormat == "CycloneDX"
        assert validated_sbom.metadata.manufacturer.name == "Test Manufacturer Inc"
        assert validated_sbom.metadata.supplier.name == "Test Supplier Corp"
        assert validated_sbom.metadata.component.name == "Test Application"
        assert len(validated_sbom.components) == 1
        assert validated_sbom.components[0].name == "dependency-lib"

    def test_full_sbom_with_manufacturer_1_7(self, component_metadata_with_manufacturer):
        """Test generating a complete CycloneDX 1.7 SBOM with manufacturer and validating against schema."""
        cdx17 = get_cyclonedx_module(CycloneDXSupportedVersion.v1_7)

        # Generate metadata
        cdx_metadata = component_metadata_with_manufacturer.to_cyclonedx(CycloneDXSupportedVersion.v1_7)

        # Add a component to the metadata
        cdx_metadata.component = cdx17.Component(
            name="Test Application 1.7",
            type=cdx17.Type.application,
            version=cdx17.Version("1.7.0"),
        )

        # Create a full SBOM
        sbom = cdx17.CyclonedxSoftwareBillOfMaterialsStandard(
            bomFormat="CycloneDX",
            specVersion="1.7",
            serialNumber="urn:uuid:12345678-1234-1234-1234-123456789012",
            version=1,
            metadata=cdx_metadata,
            components=[
                cdx17.Component(
                    name="dependency-lib-17",
                    type=cdx17.Type.library,
                    version=cdx17.Version("3.0.0"),
                )
            ],
        )

        # Serialize to JSON
        sbom_json = sbom.model_dump(mode="json", exclude_none=True, by_alias=True)

        # Validate the full SBOM can be parsed
        validated_sbom = cdx17.CyclonedxSoftwareBillOfMaterialsStandard(**sbom_json)

        assert validated_sbom.specVersion == "1.7"
        # bomFormat is an enum in 1.7
        assert validated_sbom.bomFormat.value == "CycloneDX"
        assert validated_sbom.metadata.manufacturer.name == "Test Manufacturer Inc"
        assert validated_sbom.metadata.supplier.name == "Test Supplier Corp"
        assert validated_sbom.metadata.component.name == "Test Application 1.7"
        assert len(validated_sbom.components) == 1
        assert validated_sbom.components[0].name == "dependency-lib-17"

    def test_empty_manufacturer_not_serialized(self):
        """Test that empty manufacturer is not included in output."""
        from sbomify.apps.sboms.schemas import ComponentMetaData, SupplierSchema

        metadata = ComponentMetaData(
            id="test-123",
            name="Test",
            supplier=SupplierSchema(name="Supplier"),
            manufacturer=SupplierSchema(),  # Empty manufacturer
            authors=[],
            licenses=[],
        )

        cdx16 = get_cyclonedx_module(CycloneDXSupportedVersion.v1_6)
        cdx_metadata = metadata.to_cyclonedx(CycloneDXSupportedVersion.v1_6)

        # Empty manufacturer should not be set
        assert cdx_metadata.manufacturer is None

        # But supplier should be present
        assert cdx_metadata.supplier is not None
        assert cdx_metadata.supplier.name == "Supplier"

        # Validate serialization
        serialized = cdx_metadata.model_dump(mode="json", exclude_none=True, by_alias=True)
        assert "manufacturer" not in serialized
        assert "supplier" in serialized

        validated = cdx16.Metadata(**serialized)
        assert validated.manufacturer is None
        assert validated.supplier.name == "Supplier"

    def test_cyclonedx_1_6_with_licenses(self, component_metadata_with_licenses):
        """Test CycloneDX 1.6 with licenses - verifies license handling for 1.5+ versions."""
        cdx_metadata = component_metadata_with_licenses.to_cyclonedx(CycloneDXSupportedVersion.v1_6)

        cdx16 = get_cyclonedx_module(CycloneDXSupportedVersion.v1_6)
        assert isinstance(cdx_metadata, cdx16.Metadata)

        # Licenses should be present
        assert cdx_metadata.licenses is not None

        # Serialize and validate
        serialized = cdx_metadata.model_dump(mode="json", exclude_none=True, by_alias=True)
        validated = cdx16.Metadata(**serialized)
        assert validated.licenses is not None
        assert validated.manufacturer.name == "Test Manufacturer Inc"
        assert validated.supplier.name == "Test Supplier Corp"

    def test_cyclonedx_1_7_with_licenses(self, component_metadata_with_licenses):
        """Test CycloneDX 1.7 with licenses - verifies LicenseChoice1 wrapping."""
        cdx_metadata = component_metadata_with_licenses.to_cyclonedx(CycloneDXSupportedVersion.v1_7)

        cdx17 = get_cyclonedx_module(CycloneDXSupportedVersion.v1_7)
        assert isinstance(cdx_metadata, cdx17.Metadata)

        # Licenses should be present and wrapped in LicenseChoice1
        assert cdx_metadata.licenses is not None

        # Serialize and validate - this tests the LicenseChoice1 wrapping
        serialized = cdx_metadata.model_dump(mode="json", exclude_none=True, by_alias=True)
        validated = cdx17.Metadata(**serialized)
        assert validated.licenses is not None
        assert validated.manufacturer.name == "Test Manufacturer Inc"


class TestSPDXTestFixtures:
    """Integration tests for SPDX test fixture generation."""

    def test_create_spdx_test_sbom_rejects_spdx3(self):
        """Test that SPDX 3.x versions are rejected with clear error."""
        from .fixtures import create_spdx_test_sbom

        with pytest.raises(ValueError) as exc_info:
            create_spdx_test_sbom(spdx_version="SPDX-3.0")

        assert "SPDX 2.x" in str(exc_info.value)
        assert "create_spdx3_test_sbom" in str(exc_info.value)

    def test_create_spdx_test_sbom_default(self):
        """Test default SPDX SBOM generation."""
        from .fixtures import create_spdx_test_sbom

        sbom = create_spdx_test_sbom()

        assert sbom["spdxVersion"] == "SPDX-2.3"
        assert sbom["SPDXID"] == "SPDXRef-DOCUMENT"
        assert "packages" in sbom
        assert len(sbom["packages"]) == 1

        package = sbom["packages"][0]
        assert package["name"] == "test-package"
        assert package["versionInfo"] == "1.0.0"
        assert package["supplier"] == "Organization: Test Corp"
        assert package["licenseConcluded"] == "MIT"
        assert "externalRefs" in package
        assert any(ref["referenceType"] == "purl" for ref in package["externalRefs"])

        assert "creationInfo" in sbom
        assert "created" in sbom["creationInfo"]
        assert "creators" in sbom["creationInfo"]

    def test_create_spdx_test_sbom_without_supplier(self):
        """Test SPDX SBOM generation without supplier for failure testing."""
        from .fixtures import create_spdx_test_sbom

        sbom = create_spdx_test_sbom(supplier=None)

        assert "supplier" not in sbom["packages"][0]

    def test_create_spdx_test_sbom_with_checksums(self):
        """Test SPDX SBOM with checksums for CISA compliance."""
        from .fixtures import create_spdx_test_sbom

        sbom = create_spdx_test_sbom(
            checksums=[{"algorithm": "SHA256", "checksumValue": "abc123"}]
        )

        package = sbom["packages"][0]
        assert "checksums" in package
        assert package["checksums"][0]["algorithm"] == "SHA256"

    def test_create_spdx_test_sbom_with_generation_context(self):
        """Test SPDX SBOM with generation context for CISA compliance."""
        from .fixtures import create_spdx_test_sbom

        sbom = create_spdx_test_sbom(generation_context="build")

        assert "comment" in sbom["creationInfo"]
        assert "build" in sbom["creationInfo"]["comment"].lower()

    def test_create_spdx_test_sbom_with_valid_until_date(self):
        """Test SPDX SBOM with validUntilDate for FDA/CRA compliance."""
        from .fixtures import create_spdx_test_sbom

        sbom = create_spdx_test_sbom(valid_until_date="2026-12-31")

        package = sbom["packages"][0]
        assert package["validUntilDate"] == "2026-12-31"

    def test_create_spdx_test_sbom_with_additional_packages(self):
        """Test SPDX SBOM with dependency packages."""
        from .fixtures import create_spdx_dependency_package, create_spdx_test_sbom

        dep = create_spdx_dependency_package("my-dependency", "2.0.0")
        sbom = create_spdx_test_sbom(additional_packages=[dep])

        assert len(sbom["packages"]) == 2
        assert sbom["packages"][1]["name"] == "my-dependency"

        # Check relationships include the dependency
        assert "relationships" in sbom
        dep_relationships = [
            r for r in sbom["relationships"] if r["relationshipType"] == "DEPENDS_ON"
        ]
        assert len(dep_relationships) == 1

    def test_contact_entity_to_spdx_supplier(self):
        """Test ContactEntity to SPDX supplier conversion."""
        from .fixtures import contact_entity_to_spdx_supplier

        # Test with a mock entity object
        class MockEntity:
            def __init__(self, name):
                self.name = name

        entity = MockEntity("Acme Corporation")
        result = contact_entity_to_spdx_supplier(entity)
        assert result == "Organization: Acme Corporation"

        # Test with None
        result = contact_entity_to_spdx_supplier(None)
        assert result == "NOASSERTION"

        # Test with entity without name
        entity_no_name = MockEntity(None)
        result = contact_entity_to_spdx_supplier(entity_no_name)
        assert result == "NOASSERTION"

    def test_spdx_ntia_compliant_fixture(self, spdx_sbom_ntia_compliant):
        """Test NTIA-compliant SPDX fixture has all required fields."""
        sbom = spdx_sbom_ntia_compliant

        # NTIA minimum elements
        package = sbom["packages"][0]
        assert "supplier" in package  # Supplier Name
        assert "name" in package  # Component Name
        assert "versionInfo" in package  # Version
        assert "externalRefs" in package  # Unique Identifiers

        # Relationships (Dependency Relationship)
        assert "relationships" in sbom
        assert len(sbom["relationships"]) > 0

        # SBOM Author and Timestamp
        assert "creationInfo" in sbom
        assert "creators" in sbom["creationInfo"]
        assert "created" in sbom["creationInfo"]

    def test_spdx_cisa_compliant_fixture(self, spdx_sbom_cisa_compliant):
        """Test CISA-compliant SPDX fixture has all required fields."""
        sbom = spdx_sbom_cisa_compliant

        package = sbom["packages"][0]

        # All NTIA elements
        assert "supplier" in package
        assert "name" in package
        assert "versionInfo" in package
        assert "externalRefs" in package

        # CISA additional elements
        assert "checksums" in package  # Component Hash
        assert "licenseConcluded" in package  # License

        # Tool Name (must have "Tool:" in creators)
        creators = sbom["creationInfo"]["creators"]
        assert any("Tool:" in c for c in creators)

        # Generation Context
        assert "comment" in sbom["creationInfo"]

    def test_spdx_fda_compliant_fixture(self, spdx_sbom_fda_compliant):
        """Test FDA-compliant SPDX fixture has all required fields."""
        sbom = spdx_sbom_fda_compliant

        package = sbom["packages"][0]

        # FDA-specific elements
        assert "validUntilDate" in package  # End of support date
        assert "annotations" in package  # Support status

        # Check annotation format
        annotation = package["annotations"][0]
        assert annotation["annotationType"] == "OTHER"
        assert "supportStatus" in annotation["comment"]

    def test_spdx_minimal_fixture(self, spdx_sbom_minimal):
        """Test minimal SPDX fixture is missing optional fields."""
        sbom = spdx_sbom_minimal

        package = sbom["packages"][0]

        # Should be missing these for failure testing
        assert "supplier" not in package
        assert "checksums" not in package
        assert "licenseConcluded" not in package

        # Should have no relationships
        assert "relationships" not in sbom or len(sbom.get("relationships", [])) == 0

    def test_spdx_fixture_validates_as_spdx_schema(self, spdx_sbom_ntia_compliant):
        """Test generated SPDX can be parsed by SPDXSchema."""
        # This verifies the fixture output is structurally valid
        parsed = SPDXSchema(**spdx_sbom_ntia_compliant)

        assert parsed.spdx_version == "SPDX-2.3"
        assert len(parsed.packages) > 0
        assert parsed.packages[0].name == "ntia-compliant-package"

    def test_spdx_ntia_fixture_passes_ntia_plugin(self, spdx_sbom_ntia_compliant):
        """Test NTIA-compliant fixture actually passes NTIA plugin validation."""
        import json
        import tempfile
        from pathlib import Path

        from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin

        plugin = NTIAMinimumElementsPlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(spdx_sbom_ntia_compliant, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        # All 7 NTIA elements should pass
        assert result.summary.fail_count == 0, f"Failed findings: {[f.id for f in result.findings if f.status == 'fail']}"
        assert result.summary.pass_count == 7  # 7 NTIA minimum elements

    def test_spdx_cisa_fixture_passes_cisa_plugin(self, spdx_sbom_cisa_compliant):
        """Test CISA-compliant fixture actually passes CISA plugin validation."""
        import json
        import tempfile
        from pathlib import Path

        from sbomify.apps.plugins.builtins.cisa import CISAMinimumElementsPlugin

        plugin = CISAMinimumElementsPlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(spdx_sbom_cisa_compliant, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        # All 11 CISA elements should pass
        assert result.summary.fail_count == 0, f"Failed findings: {[f.id for f in result.findings if f.status == 'fail']}"
        assert result.summary.pass_count == 11  # 11 CISA 2025 elements

    def test_spdx_minimal_fixture_fails_ntia_plugin(self, spdx_sbom_minimal):
        """Test minimal fixture correctly fails NTIA plugin validation."""
        import json
        import tempfile
        from pathlib import Path

        from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin

        plugin = NTIAMinimumElementsPlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(spdx_sbom_minimal, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        # Should fail on supplier and relationships at minimum
        assert result.summary.fail_count > 0
        failed_ids = [f.id for f in result.findings if f.status == "fail"]
        assert "ntia-2021:supplier-name" in failed_ids
        assert "ntia-2021:dependency-relationship" in failed_ids

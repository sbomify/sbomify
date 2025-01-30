import pytest

from ..schemas import (
    CustomLicenseSchema,
    CycloneDXSupportedVersion,
    SPDXPackage,
    SPDXSchema,
    get_cyclonedx_module,
)


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
        "specVersion": "1.5",
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
    assert get_cyclonedx_module(CycloneDXSupportedVersion.v1_5).__name__ == "sboms.sbom_format_schemas.cyclonedx_1_5"
    assert get_cyclonedx_module(CycloneDXSupportedVersion.v1_6).__name__ == "sboms.sbom_format_schemas.cyclonedx_1_6"


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

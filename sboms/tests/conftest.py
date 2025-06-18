import pytest

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
def sample_cyclonedx_schema_dict(sample_cyclonedx_component_dict):
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
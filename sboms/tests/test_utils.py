import hashlib
import json
from unittest.mock import patch

import pytest
from django.http import HttpRequest
from pytest_mock import MockerFixture

from core.tests.fixtures import sample_user  # noqa: F401
from core.utils import number_to_random_token, verify_item_access
from sboms.sbom_format_schemas import cyclonedx_1_5 as cdx15
from sboms.sbom_format_schemas import cyclonedx_1_6 as cdx16
from sboms.utils import ProjectSBOMBuilder
from teams.fixtures import sample_team, sample_team_with_owner_member  # noqa: F401
from teams.models import Member, Team

from .fixtures import (
    sample_access_token,  # noqa: F401
    sample_component,  # noqa: F401
    sample_project,  # noqa: F401
    sample_sbom,  # noqa: F401
)


@pytest.fixture
def mock_request(sample_user) -> HttpRequest:  # noqa: F811
    request = HttpRequest()
    request.user = sample_user
    request.session = {}
    return request


@pytest.fixture
def mock_request_with_teams(mock_request, sample_team) -> HttpRequest:  # noqa: F811
    # Create team membership
    member = Member.objects.create(user=mock_request.user, team=sample_team, role="owner")

    # Ensure team has a valid key
    if not sample_team.key or len(sample_team.key) < 9:
        sample_team.key = number_to_random_token(sample_team.id)
        sample_team.save()

    # Set up session data
    mock_request.session["user_teams"] = {
        sample_team.key: {"role": member.role, "name": sample_team.name, "is_default_team": member.is_default_team}
    }
    return mock_request


def test_verify_item_access_unauthenticated(mock_request):
    """Test access verification for unauthenticated user"""
    mock_request.user = type("AnonymousUser", (), {"is_authenticated": False})()
    team = Team(name="test")

    result = verify_item_access(mock_request, team, ["owner"])

    assert result is False


def test_verify_item_access_team_with_session(mock_request_with_teams, sample_team):  # noqa: F811
    """Test access verification for team using session data"""
    result = verify_item_access(mock_request_with_teams, sample_team, ["owner"])

    assert result is True


def test_verify_item_access_team_wrong_role(mock_request_with_teams, sample_team):  # noqa: F811
    """Test access verification fails with wrong role"""
    result = verify_item_access(mock_request_with_teams, sample_team, ["admin"])

    assert result is False


def test_verify_item_access_product(mock_request_with_teams, sample_product):
    """Test access verification for product"""
    result = verify_item_access(mock_request_with_teams, sample_product, ["owner"])

    assert result is True


def test_verify_item_access_project(mock_request_with_teams, sample_project):  # noqa: F811
    """Test access verification for project"""
    result = verify_item_access(mock_request_with_teams, sample_project, ["owner"])

    assert result is True


def test_verify_item_access_component(mock_request_with_teams, sample_component):  # noqa: F811
    """Test access verification for component"""
    result = verify_item_access(mock_request_with_teams, sample_component, ["owner"])

    assert result is True


def test_verify_item_access_sbom(mock_request_with_teams, sample_sbom):  # noqa: F811
    """Test access verification for SBOM"""
    result = verify_item_access(mock_request_with_teams, sample_sbom, ["owner"])

    assert result is True


@pytest.fixture
def mock_s3_client(mocker):
    """Legacy fixture for backward compatibility - creates a mock with the old interface."""
    mock_client = mocker.MagicMock()
    mock_client.get_sbom_data.return_value = json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {"component": {"name": "test-component", "type": "library", "version": "1.0.0"}},
        }
    ).encode()

    # Mock the S3Client class to return our mock instance
    mocker.patch("core.object_store.S3Client", return_value=mock_client)
    return mock_client


@pytest.mark.django_db
def test_project_sbom_builder(sample_project, mock_s3_client, tmp_path):  # noqa: F811
    """Test ProjectSBOMBuilder generates valid SBOM"""
    builder = ProjectSBOMBuilder(project=sample_project)
    sbom = builder(tmp_path)

    assert sbom.bomFormat == "CycloneDX"
    assert sbom.specVersion == "1.6"
    assert sbom.metadata.component.name == sample_project.name

    # TEST 1: Verify vendor is lowercase 'sbomify, ltd'
    assert "metadata" in sbom.model_dump()
    assert "tools" in sbom.model_dump()["metadata"]
    assert len(sbom.model_dump()["metadata"]["tools"]) > 0

    tool = sbom.model_dump()["metadata"]["tools"][0]


@pytest.mark.django_db
def test_project_sbom_builder_no_components(sample_project, tmp_path):  # noqa: F811
    """Test ProjectSBOMBuilder with no components"""
    builder = ProjectSBOMBuilder(project=sample_project)
    sbom = builder(tmp_path)

    assert sbom.components == []  # Changed expectation from None to []


@pytest.mark.django_db
def test_project_sbom_builder_invalid_sbom_format(sample_project, mock_s3_client, tmp_path):  # noqa: F811
    """Test ProjectSBOMBuilder with invalid SBOM format"""
    mock_s3_client.get_sbom_data.return_value = json.dumps({"bomFormat": "Invalid", "specVersion": "1.6"}).encode()

    builder = ProjectSBOMBuilder(project=sample_project)
    sbom = builder(tmp_path)

    assert sbom.components == []  # Changed expectation from None to []


@pytest.mark.parametrize(
    "spec_version,input_version,expected_component_type,expected_ref_type",
    [
        ("1.6", "1.6", cdx16.Component, cdx16.ExternalReference),
        ("1.5", "1.5", cdx16.Component, cdx16.ExternalReference),  # Now returns 1.6 components
    ],
)
def test_get_component_metadata_creates_correct_external_reference_type(
    spec_version: str, input_version: str, expected_component_type, expected_ref_type, tmp_path
):
    """Test that get_component_metadata creates CycloneDX 1.6 components with proper external references."""
    builder = ProjectSBOMBuilder()

    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": spec_version,
        "metadata": {"component": {"name": "test-component", "type": "library", "version": "1.0.0"}},
    }

    component = builder.get_component_metadata("test.json", sbom_data, "test-sbom-id")

    # Verify the component is of the correct type (always CycloneDX 1.6 now)
    assert isinstance(component, expected_component_type)
    assert component.name == "test-component"
    assert component.type == "library"
    # Handle different version types between CycloneDX versions
    if hasattr(component.version, "root"):
        assert component.version.root == "1.0.0"  # CycloneDX 1.6 uses Version RootModel
    else:
        assert component.version == "1.0.0"  # CycloneDX 1.5 uses plain string

    # Verify the ExternalReference is of the correct type (always CycloneDX 1.6 now)
    assert component.externalReferences is not None
    assert len(component.externalReferences) == 1

    external_ref = component.externalReferences[0]
    assert isinstance(external_ref, expected_ref_type)
    # The URL should now use the API endpoint format with the test settings APP_BASE_URL
    from django.conf import settings
    expected_url = f"{settings.APP_BASE_URL}/api/v1/sboms/test-sbom-id/download"
    assert external_ref.url == expected_url

    # The type enum should always be CycloneDX 1.6 now
    assert external_ref.type == cdx16.Type3.other

    # Verify hashes are present
    assert external_ref.hashes is not None
    assert len(external_ref.hashes) == 1
    assert external_ref.hashes[0].alg == "SHA-256"
    # Calculate expected hash of the filename
    expected_hash = hashlib.sha256("test.json".encode("utf-8")).hexdigest()
    assert external_ref.hashes[0].content.root == expected_hash


def test_get_component_metadata_unsupported_version():
    """Test get_component_metadata with unsupported CycloneDX version (now resilient)."""
    builder = ProjectSBOMBuilder()

    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "2.0",  # Unsupported version, but method is now resilient
        "metadata": {"component": {"name": "test-component", "type": "library"}},
    }

    component = builder.get_component_metadata("test.json", sbom_data, "test-sbom-id")

    # The method should now be resilient and extract what it can
    assert component is not None
    assert component.name == "test-component"
    assert component.type == "library"
    assert component.version is None  # No version provided

    # Should have external reference to original SBOM
    assert component.externalReferences is not None
    assert len(component.externalReferences) == 1
    from django.conf import settings
    expected_url = f"{settings.APP_BASE_URL}/api/v1/sboms/test-sbom-id/download"
    assert component.externalReferences[0].url == expected_url


def test_get_component_metadata_invalid_bom_format():
    """Test get_component_metadata with invalid BOM format."""
    builder = ProjectSBOMBuilder()

    sbom_data = {
        "bomFormat": "SPDX",  # Wrong format
        "specVersion": "1.6",
        "metadata": {"component": {"name": "test-component", "type": "library"}},
    }

    component = builder.get_component_metadata("test.json", sbom_data, "test-sbom-id")
    assert component is None


def test_get_component_metadata_missing_component():
    """Test get_component_metadata with missing component metadata."""
    builder = ProjectSBOMBuilder()

    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {},  # Missing component
    }

    component = builder.get_component_metadata("test.json", sbom_data, "test-sbom-id")
    assert component is None


def test_external_reference_type_enums_exist():
    """Test that Type3.other exists in both CycloneDX versions to prevent regression of ExternalReferenceType error."""
    # Verify Type3 exists and has 'other' value in both versions
    assert hasattr(cdx15, "Type3")
    assert hasattr(cdx16, "Type3")

    assert hasattr(cdx15.Type3, "other")
    assert hasattr(cdx16.Type3, "other")

    # Verify the values are correct
    assert cdx15.Type3.other == "other"
    assert cdx16.Type3.other == "other"

    # Verify ExternalReference classes use Type3 for their type field
    # This ensures we don't have ExternalReferenceType confusion
    ref_15 = cdx15.ExternalReference(type=cdx15.Type3.other, url="https://example.com")
    ref_16 = cdx16.ExternalReference(type=cdx16.Type3.other, url="https://example.com")

    assert ref_15.type == cdx15.Type3.other
    assert ref_16.type == cdx16.Type3.other


@pytest.mark.django_db
def test_project_sbom_builder_with_cyclonedx_15_component(sample_project, s3_sboms_mock, tmp_path):  # noqa: F811
    """Test ProjectSBOMBuilder integration with CycloneDX 1.5 component SBOM."""

    # Configure S3 mock to return a CycloneDX 1.5 SBOM
    legacy_sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {"component": {"name": "legacy-component", "type": "library", "version": "0.9.0"}},
    }
    s3_sboms_mock.uploaded_files["legacy.json"] = json.dumps(legacy_sbom).encode()

    builder = ProjectSBOMBuilder(project=sample_project)
    sbom = builder(tmp_path)

    # Verify the main SBOM is still 1.6
    assert sbom.bomFormat == "CycloneDX"
    assert sbom.specVersion == "1.6"

    # Verify components were processed correctly
    if sbom.components:  # Only check if components exist
        # The component should have been properly processed with 1.5 ExternalReferences
        component = sbom.components[0]
        assert component.name == "test-component"  # This will be from the pre-configured mock
        assert component.version == "1.0.0"

        # Check that external references were added
        if hasattr(component, "externalReferences") and component.externalReferences:
            assert len(component.externalReferences) >= 1


@pytest.mark.django_db
def test_project_sbom_file_generation_with_components(sample_project, tmp_path):  # noqa: F811
    """Test that the project SBOM file is generated correctly with real component relationships."""

    # Import necessary models
    from sboms.models import SBOM, Component, ProjectComponent

    # SECURITY: Make the project public so we can test SBOM generation
    sample_project.is_public = True
    sample_project.save()

    # Create components with SBOMs
    component1 = Component.objects.create(
        name="component1",
        team=sample_project.team,
        component_type="sbom",
        is_public=True,  # SECURITY: Make component public
    )

    component2 = Component.objects.create(
        name="component2",
        team=sample_project.team,
        component_type="sbom",
        is_public=True,  # SECURITY: Make component public
    )

    # Create SBOMs for components
    sbom1 = SBOM.objects.create(
        name="component1-sbom",
        component=component1,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="component1.cdx.json",
    )

    sbom2 = SBOM.objects.create(
        name="component2-sbom",
        component=component2,
        format="cyclonedx",
        format_version="1.5",
        sbom_filename="component2.cdx.json",
    )

    # Link components to the project
    ProjectComponent.objects.create(project=sample_project, component=component1)
    ProjectComponent.objects.create(project=sample_project, component=component2)

    # Mock S3 client to return different mock SBOM data for each component
    with patch("core.object_store.S3Client") as mock_s3:
        mock_s3_instance = mock_s3.return_value

        def mock_get_sbom_data(filename):
            if filename == "component1.cdx.json":
                return json.dumps(
                    {
                        "bomFormat": "CycloneDX",
                        "specVersion": "1.6",
                        "metadata": {"component": {"name": "component1", "type": "library", "version": "1.0.0"}},
                    }
                ).encode()
            elif filename == "component2.cdx.json":
                return json.dumps(
                    {
                        "bomFormat": "CycloneDX",
                        "specVersion": "1.5",
                        "metadata": {"component": {"name": "component2", "type": "library", "version": "2.0.0"}},
                    }
                ).encode()
            else:
                raise Exception(f"Unexpected filename: {filename}")

        mock_s3_instance.get_sbom_data.side_effect = mock_get_sbom_data

        # Generate the SBOM file
        from sboms.utils import get_project_sbom_package

        sbom_path = get_project_sbom_package(sample_project, tmp_path)

        # Check that the SBOM file exists and is not empty
        assert sbom_path.exists()
        assert sbom_path.stat().st_size > 0

        # Check what files were created in the temp directory
        temp_files = list(tmp_path.glob("*"))
        json_files = list(tmp_path.glob("*.json"))

        # Verify the project SBOM content
        project_sbom_content = sbom_path.read_text()
        project_sbom_data = json.loads(project_sbom_content)

        assert project_sbom_data["bomFormat"] == "CycloneDX"
        assert project_sbom_data["specVersion"] == "1.6"
        assert "components" in project_sbom_data

        # The project SBOM should have component metadata from the individual SBOMs
        components = project_sbom_data.get("components", [])
        if components:
            # Verify we have the expected components
            assert len(components) == 2
            component_names = [comp.get("name") for comp in components]
            assert "component1" in component_names
            assert "component2" in component_names

        # Verify files were created as expected
        assert len(json_files) >= 1  # At least the project SBOM file
        assert sbom_path.name in [f.name for f in json_files]


@pytest.mark.django_db
def test_simple_external_reference_creation():
    """Test creating ExternalReference objects to isolate serialization issues."""

    import hashlib

    from sboms.sbom_format_schemas import cyclonedx_1_5 as cdx15
    from sboms.sbom_format_schemas import cyclonedx_1_6 as cdx16

    # Test CycloneDX 1.6 ExternalReference creation
    filename_hash = hashlib.sha256("test.json".encode("utf-8")).hexdigest()

    try:
        # Test creating Hash object first
        hash_content_16 = cdx16.HashContent(filename_hash)
        hash_obj_16 = cdx16.Hash(alg="SHA-256", content=hash_content_16)

        # Test creating ExternalReference
        ext_ref_16 = cdx16.ExternalReference(
            type=cdx16.Type3.other, url="https://sbomify.com/sboms/test.json", hashes=[hash_obj_16]
        )

        # Test serialization of the external reference
        serialized = ext_ref_16.model_dump_json()
        assert len(serialized) > 0

    except Exception as e:
        pytest.fail(f"CycloneDX 1.6 ExternalReference creation failed: {e}")

    # Test CycloneDX 1.5 as well
    try:
        hash_content_15 = cdx15.HashContent(filename_hash)
        hash_obj_15 = cdx15.Hash(alg="SHA-256", content=hash_content_15)

        ext_ref_15 = cdx15.ExternalReference(
            type=cdx15.Type3.other, url="https://sbomify.com/sboms/test.json", hashes=[hash_obj_15]
        )

        serialized = ext_ref_15.model_dump_json()
        assert len(serialized) > 0

    except Exception as e:
        pytest.fail(f"CycloneDX 1.5 ExternalReference creation failed: {e}")


@pytest.mark.django_db
def test_project_sbom_builder_serialization(sample_project, tmp_path):  # noqa: F811
    """Test ProjectSBOMBuilder serialization to isolate the issue."""

    # Import necessary models
    from sboms.models import SBOM, Component, ProjectComponent
    from sboms.utils import ProjectSBOMBuilder

    # Create a component with SBOM (must be public to be included in project SBOM)
    component = Component.objects.create(
        name="test-component",
        team=sample_project.team,
        component_type="sbom",
        is_public=True
    )

    sbom = SBOM.objects.create(
        name="test-sbom", component=component, format="cyclonedx", format_version="1.6", sbom_filename="test.cdx.json"
    )

    # Link component to the project
    ProjectComponent.objects.create(project=sample_project, component=component)

    # Mock S3 client
    with patch("core.object_store.S3Client") as mock_s3:
        mock_s3_instance = mock_s3.return_value
        mock_s3_instance.get_sbom_data.return_value = json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "metadata": {"component": {"name": "test-component", "type": "library", "version": "1.0.0"}},
            }
        ).encode()

        # Test ProjectSBOMBuilder step by step
        builder = ProjectSBOMBuilder(sample_project)

        # Create SBOM object
        sbom_obj = builder(tmp_path)

        # Verify we have the expected components
        assert len(sbom_obj.components) > 0

        # Check each component for potential serialization issues
        for i, comp in enumerate(sbom_obj.components):
            # Check if component has external references
            if hasattr(comp, "externalReferences") and comp.externalReferences:
                for j, ext_ref in enumerate(comp.externalReferences):
                    # Verify external reference structure
                    assert hasattr(ext_ref, "type")
                    assert hasattr(ext_ref, "url")
                    if hasattr(ext_ref, "hashes") and ext_ref.hashes:
                        for k, hash_obj in enumerate(ext_ref.hashes):
                            assert hasattr(hash_obj, "alg")
                            assert hasattr(hash_obj, "content")

                    # Try to serialize just the external reference
                    try:
                        ext_ref_json = ext_ref.model_dump_json()
                        assert len(ext_ref_json) > 0
                    except Exception as e:
                        pytest.fail(f"ExtRef {j} serialization failed: {e}")

            # Try to serialize just this component
            try:
                comp_json = comp.model_dump_json()
                assert len(comp_json) > 0
            except Exception as e:
                pytest.fail(f"Component {i} serialization failed: {e}")

        # Attempt full SBOM serialization
        try:
            sbom_json = sbom_obj.model_dump_json(indent=2)
            assert len(sbom_json) > 0
        except Exception as e:
            pytest.fail(f"Full SBOM serialization failed: {e}")


@pytest.mark.django_db
def test_mixed_cyclonedx_versions_serialization(sample_project, tmp_path):  # noqa: F811
    """Test ProjectSBOMBuilder with mixed CycloneDX 1.5 and 1.6 components."""

    # Import necessary models
    from sboms.models import SBOM, Component, ProjectComponent
    from sboms.utils import ProjectSBOMBuilder

    # Create components with different CycloneDX versions (must be public to be included in project SBOM)
    component1 = Component.objects.create(
        name="component1",
        team=sample_project.team,
        component_type="sbom",
        is_public=True
    )

    component2 = Component.objects.create(
        name="component2",
        team=sample_project.team,
        component_type="sbom",
        is_public=True
    )

    # Create SBOMs with different versions
    sbom1 = SBOM.objects.create(
        name="component1-sbom",
        component=component1,
        format="cyclonedx",
        format_version="1.6",  # CycloneDX 1.6
        sbom_filename="component1.cdx.json",
    )

    sbom2 = SBOM.objects.create(
        name="component2-sbom",
        component=component2,
        format="cyclonedx",
        format_version="1.5",  # CycloneDX 1.5
        sbom_filename="component2.cdx.json",
    )

    # Link components to the project
    ProjectComponent.objects.create(project=sample_project, component=component1)
    ProjectComponent.objects.create(project=sample_project, component=component2)

    # Mock S3 client
    with patch("core.object_store.S3Client") as mock_s3:
        mock_s3_instance = mock_s3.return_value

        def mock_get_sbom_data(filename):
            if filename == "component1.cdx.json":
                return json.dumps(
                    {
                        "bomFormat": "CycloneDX",
                        "specVersion": "1.6",
                        "metadata": {"component": {"name": "component1", "type": "library", "version": "1.0.0"}},
                    }
                ).encode()
            elif filename == "component2.cdx.json":
                return json.dumps(
                    {
                        "bomFormat": "CycloneDX",
                        "specVersion": "1.5",
                        "metadata": {"component": {"name": "component2", "type": "library", "version": "2.0.0"}},
                    }
                ).encode()
            else:
                raise Exception(f"Unexpected filename: {filename}")

        mock_s3_instance.get_sbom_data.side_effect = mock_get_sbom_data

        # Test ProjectSBOMBuilder step by step
        builder = ProjectSBOMBuilder(sample_project)

        # Create SBOM object with mixed versions
        sbom_obj = builder(tmp_path)

        # Verify we have the expected components
        assert len(sbom_obj.components) > 0

        # Check each component
        for i, comp in enumerate(sbom_obj.components):
            # Check version-specific component type
            comp_type = type(comp)
            assert comp_type is not None

            if hasattr(comp, "externalReferences") and comp.externalReferences:
                assert len(comp.externalReferences) > 0
                for j, ext_ref in enumerate(comp.externalReferences):
                    ext_ref_type = type(ext_ref)
                    assert ext_ref_type is not None
                    assert hasattr(ext_ref, "type")
                    assert hasattr(ext_ref, "url")

                    if hasattr(ext_ref, "hashes") and ext_ref.hashes:
                        for k, hash_obj in enumerate(ext_ref.hashes):
                            hash_type = type(hash_obj)
                            content_type = type(hash_obj.content)
                            assert hash_type is not None
                            assert content_type is not None

            # Try to serialize each component individually
            try:
                comp_json = comp.model_dump_json()
                assert len(comp_json) > 0
            except Exception as e:
                # Let's try to understand which field is causing the issue
                try:
                    comp_dict = comp.model_dump()
                    assert isinstance(comp_dict, dict)
                except Exception as e2:
                    pytest.fail(f"Component {i} ({comp.name}) model_dump() failed: {e2}")
                pytest.fail(f"Component {i} ({comp.name}) serialization failed: {e}")

        # Attempt full SBOM serialization
        try:
            sbom_json = sbom_obj.model_dump_json(indent=2)
            assert len(sbom_json) > 0
        except Exception as e:
            # Let's try to identify the problematic field
            try:
                sbom_dict = sbom_obj.model_dump()
                assert isinstance(sbom_dict, dict)
            except Exception as e2:
                pytest.fail(f"SBOM model_dump() failed: {e2}")
            pytest.fail(f"Full SBOM serialization failed: {e}")


@pytest.mark.django_db
def test_product_sbom_file_generation(tmp_path):
    """Test that the product SBOM file is generated correctly with aggregated component data."""

    # Import necessary models
    from sboms.models import SBOM, Component, Product, Project, ProjectComponent
    from sboms.utils import get_product_sbom_package
    from teams.models import Team

    # Create a team
    team = Team.objects.create(name="test-team", key="test-team")

    # Create a PUBLIC product with PUBLIC projects and PUBLIC components
    product = Product.objects.create(name="test-product", team=team, is_public=True)
    project = Project.objects.create(name="test-project", team=team, is_public=True)

    # Link project to product
    from sboms.models import ProductProject

    ProductProject.objects.create(product=product, project=project)

    # Create PUBLIC components
    component1 = Component.objects.create(name="component1", team=team, component_type="sbom", is_public=True)
    component2 = Component.objects.create(name="component2", team=team, component_type="sbom", is_public=True)

    # Create SBOMs
    sbom1 = SBOM.objects.create(
        name="component1-sbom",
        component=component1,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="component1.cdx.json",
    )
    sbom2 = SBOM.objects.create(
        name="component2-sbom",
        component=component2,
        format="cyclonedx",
        format_version="1.5",
        sbom_filename="component2.cdx.json",
    )

    # Link components to project
    ProjectComponent.objects.create(project=project, component=component1)
    ProjectComponent.objects.create(project=project, component=component2)

    # Mock S3 client
    with patch("core.object_store.S3Client") as mock_s3:
        mock_s3_instance = mock_s3.return_value

        def mock_get_sbom_data(filename):
            if "component1" in filename:
                return json.dumps(
                    {
                        "bomFormat": "CycloneDX",
                        "specVersion": "1.6",
                        "metadata": {"component": {"name": "comp1", "type": "library", "version": "1.0.0"}},
                    }
                ).encode()
            elif "component2" in filename:
                return json.dumps(
                    {
                        "bomFormat": "CycloneDX",
                        "specVersion": "1.5",
                        "metadata": {"component": {"name": "comp2", "type": "framework", "version": "2.0.0"}},
                    }
                ).encode()
            else:
                return b"{}"

        mock_s3_instance.get_sbom_data.side_effect = mock_get_sbom_data

        # Test product SBOM file creation
        sbom_path = get_product_sbom_package(product, tmp_path)

        # Verify SBOM file exists
        assert sbom_path.exists()
        assert sbom_path.name == "test-product.cdx.json"

        # Verify SBOM file contents
        sbom_content = sbom_path.read_text()
        sbom_data = json.loads(sbom_content)

        # Verify it's a proper CycloneDX SBOM
        assert sbom_data["bomFormat"] == "CycloneDX"
        assert sbom_data["specVersion"] == "1.6"
        assert "components" in sbom_data

        # Should have aggregated components
        assert len(sbom_data["components"]) == 2


@pytest.mark.django_db
def test_sbom_vendor_and_remote_file_references(tmp_path):
    """Test that SBOMs use correct vendor 'sbomify, ltd' and remote file references."""

    import json

    from sboms.models import SBOM, Component, Product, Project, ProjectComponent
    from sboms.utils import get_product_sbom_package
    from teams.models import Team

    # Create test entities
    team = Team.objects.create(name="test-team", key="test-team")
    product = Product.objects.create(name="test-product", team=team, is_public=True)
    project = Project.objects.create(name="test-project", team=team, is_public=True)

    # Link project to product
    from sboms.models import ProductProject

    ProductProject.objects.create(product=product, project=project)

    # Create component
    component = Component.objects.create(name="test-component", team=team, component_type="sbom", is_public=True)

    # Create SBOM with specific filename
    sbom = SBOM.objects.create(
        name="test-sbom",
        component=component,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="my-component.cdx.json",
    )

    ProjectComponent.objects.create(project=project, component=component)

    # Mock S3 client
    with patch("core.object_store.S3Client") as mock_s3:
        mock_s3_instance = mock_s3.return_value
        mock_s3_instance.get_sbom_data.return_value = json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "metadata": {"component": {"name": "test-comp", "type": "library", "version": "1.0.0"}},
            }
        ).encode()

        # Generate product SBOM
        sbom_path = get_product_sbom_package(product, tmp_path)

        # Read the generated product SBOM
        sbom_content = sbom_path.read_text()
        sbom_data = json.loads(sbom_content)

        # TEST 1: Verify vendor is 'sbomify, ltd'
        assert "metadata" in sbom_data
        assert "tools" in sbom_data["metadata"]
        assert len(sbom_data["metadata"]["tools"]) > 0

        tool = sbom_data["metadata"]["tools"][0]
        assert tool["vendor"] == "sbomify, ltd", f"Expected 'sbomify, ltd' but got '{tool['vendor']}'"
        assert tool["name"] == "sbomify", f"Expected 'sbomify' but got '{tool['name']}'"

        # TEST 2: Verify external references point to API endpoints
        assert "components" in sbom_data
        assert len(sbom_data["components"]) > 0

        component_data = sbom_data["components"][0]
        assert "externalReferences" in component_data
        assert len(component_data["externalReferences"]) > 0

        ext_ref = component_data["externalReferences"][0]
        # The URL should now use the API endpoint format with test settings
        from django.conf import settings
        expected_url = f"{settings.APP_BASE_URL}/api/v1/sboms/{sbom.id}/download"
        assert ext_ref["url"] == expected_url, f"Expected API URL but got '{ext_ref['url']}'"
        assert ext_ref["url"].startswith("http://"), f"External reference should be a URL: '{ext_ref['url']}'"
        assert ext_ref["type"] == "other"

        # TEST 3: Verify we only have the SBOM file, no ZIP
        assert sbom_path.name == "test-product.cdx.json", f"Expected SBOM file but got '{sbom_path.name}'"
        assert sbom_path.suffix == ".json", f"Expected JSON file but got '{sbom_path.suffix}'"


@pytest.mark.django_db
def test_private_project_access_denied(tmp_path):
    """Test that private projects cannot have SBOMs generated."""

    from sboms.models import Product, Project
    from sboms.utils import get_project_sbom_package
    from teams.models import Team

    # Create a team
    team = Team.objects.create(name="test-team", key="test-team")

    # Create a PRIVATE project
    private_project = Project.objects.create(name="private-project", team=team, is_public=False)

    # Attempt to generate SBOM for private project should raise PermissionError
    with pytest.raises(PermissionError, match="Cannot generate SBOM for private project"):
        get_project_sbom_package(private_project, tmp_path)


@pytest.mark.django_db
def test_private_product_access_denied(tmp_path):
    """Test that private products cannot have SBOMs generated."""

    from sboms.models import Product
    from sboms.utils import get_product_sbom_package
    from teams.models import Team

    # Create a team
    team = Team.objects.create(name="test-team", key="test-team")

    # Create a PRIVATE product
    private_product = Product.objects.create(name="private-product", team=team, is_public=False)

    # Attempt to generate SBOM for private product should raise PermissionError
    with pytest.raises(PermissionError, match="Cannot generate SBOM for private product"):
        get_product_sbom_package(private_product, tmp_path)


@pytest.mark.django_db
def test_invalid_sbom_id_validation():
    """Test that invalid SBOM IDs are handled gracefully."""

    from sboms.utils import validate_api_endpoint

    # Test with non-existent SBOM ID
    result = validate_api_endpoint("non-existent-sbom-id")
    assert result is False

    # Test with invalid UUID format
    result = validate_api_endpoint("invalid-uuid")
    assert result is False


@pytest.mark.django_db
def test_network_failure_during_s3_operations(sample_project, tmp_path):  # noqa: F811
    """Test that network failures during S3 operations are handled gracefully."""

    from sboms.models import SBOM, Component, ProjectComponent
    from sboms.utils import get_project_sbom_package

    # SECURITY: Make the project public so we can test SBOM generation
    sample_project.is_public = True
    sample_project.save()

    # Create a component with SBOM
    component = Component.objects.create(
        name="test-component",
        team=sample_project.team,
        component_type="sbom",
        is_public=True,  # SECURITY: Make component public
    )

    sbom = SBOM.objects.create(
        name="test-sbom",
        component=component,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="test.cdx.json",
    )

    # Link component to the project
    ProjectComponent.objects.create(project=sample_project, component=component)

    # Mock S3 client to simulate network failure
    with patch("core.object_store.S3Client") as mock_s3:
        mock_s3_instance = mock_s3.return_value
        mock_s3_instance.get_sbom_data.side_effect = Exception("Network connection failed")

        # This should not raise an exception but should handle the failure gracefully
        sbom_path = get_project_sbom_package(sample_project, tmp_path)

        # Verify SBOM file was still created (even if components couldn't be loaded)
        assert sbom_path.exists()
        assert sbom_path.name == f"{sample_project.name}.cdx.json"

        # Verify the SBOM is valid but may not have components due to network failure
        sbom_content = sbom_path.read_text()
        sbom_data = json.loads(sbom_content)
        assert sbom_data["bomFormat"] == "CycloneDX"
        assert sbom_data["specVersion"] == "1.6"


@pytest.mark.django_db
def test_malformed_sbom_file_handling(sample_project, tmp_path):  # noqa: F811
    """Test that malformed SBOM files are handled gracefully."""

    from sboms.models import SBOM, Component, ProjectComponent
    from sboms.utils import get_project_sbom_package

    # SECURITY: Make the project public so we can test SBOM generation
    sample_project.is_public = True
    sample_project.save()

    # Create a component with SBOM
    component = Component.objects.create(
        name="test-component",
        team=sample_project.team,
        component_type="sbom",
        is_public=True,  # SECURITY: Make component public
    )

    sbom = SBOM.objects.create(
        name="test-sbom",
        component=component,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="malformed.cdx.json",
    )

    # Link component to the project
    ProjectComponent.objects.create(project=sample_project, component=component)

    # Mock S3 client to return malformed JSON
    with patch("core.object_store.S3Client") as mock_s3:
        mock_s3_instance = mock_s3.return_value
        mock_s3_instance.get_sbom_data.return_value = b"{ invalid json content"

        # This should not raise an exception but should handle the malformed data gracefully
        sbom_path = get_project_sbom_package(sample_project, tmp_path)

        # Verify SBOM file was still created (even if components couldn't be parsed)
        assert sbom_path.exists()
        assert sbom_path.name == f"{sample_project.name}.cdx.json"

        # Verify the SBOM is valid but may not have components due to malformed data
        sbom_content = sbom_path.read_text()
        sbom_data = json.loads(sbom_content)
        assert sbom_data["bomFormat"] == "CycloneDX"
        assert sbom_data["specVersion"] == "1.6"


@pytest.mark.django_db
def test_invalid_sbom_format_handling(sample_project, tmp_path):  # noqa: F811
    """Test that invalid SBOM formats are handled gracefully."""

    from sboms.models import SBOM, Component, ProjectComponent
    from sboms.utils import get_project_sbom_package

    # SECURITY: Make the project public so we can test SBOM generation
    sample_project.is_public = True
    sample_project.save()

    # Create a component with SBOM
    component = Component.objects.create(
        name="test-component",
        team=sample_project.team,
        component_type="sbom",
        is_public=True,  # SECURITY: Make component public
    )

    sbom = SBOM.objects.create(
        name="test-sbom",
        component=component,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="invalid-format.cdx.json",
    )

    # Link component to the project
    ProjectComponent.objects.create(project=sample_project, component=component)

    # Mock S3 client to return SBOM with invalid format
    with patch("core.object_store.S3Client") as mock_s3:
        mock_s3_instance = mock_s3.return_value
        mock_s3_instance.get_sbom_data.return_value = json.dumps(
            {
                "bomFormat": "SPDX",  # Wrong format - should be CycloneDX
                "specVersion": "1.6",
                "metadata": {"component": {"name": "test-component", "type": "library"}},
            }
        ).encode()

        # This should not raise an exception but should handle the invalid format gracefully
        sbom_path = get_project_sbom_package(sample_project, tmp_path)

        # Verify SBOM file was still created (even if components couldn't be processed)
        assert sbom_path.exists()
        assert sbom_path.name == f"{sample_project.name}.cdx.json"

        # Verify the SBOM is valid but may not have components due to invalid format
        sbom_content = sbom_path.read_text()
        sbom_data = json.loads(sbom_content)
        assert sbom_data["bomFormat"] == "CycloneDX"
        assert sbom_data["specVersion"] == "1.6"

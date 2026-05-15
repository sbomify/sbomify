import hashlib
import json
from unittest.mock import patch

import pytest
from django.http import HttpRequest

from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.core.utils import number_to_random_token, verify_item_access
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.sbom_format_schemas import cyclonedx_1_5 as cdx15
from sbomify.apps.sboms.sbom_format_schemas import cyclonedx_1_6 as cdx16
from sbomify.apps.sboms.utils import ProductSBOMBuilder
from sbomify.apps.teams.fixtures import sample_team, sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import Member, Team

from .fixtures import (
    sample_access_token,  # noqa: F401
    sample_component,  # noqa: F401
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
    mocker.patch("sbomify.apps.core.object_store.S3Client", return_value=mock_client)
    return mock_client


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
    builder = ProductSBOMBuilder()

    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": spec_version,
        "metadata": {"component": {"name": "test-component", "type": "library", "version": "1.0.0"}},
    }

    component = builder.get_component_metadata("test.json", sbom_data, "", "test-sbom-id")

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
    builder = ProductSBOMBuilder()

    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "2.0",  # Unsupported version, but method is now resilient
        "metadata": {"component": {"name": "test-component", "type": "library"}},
    }

    component = builder.get_component_metadata("test.json", sbom_data, "", "test-sbom-id")

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
    builder = ProductSBOMBuilder()

    sbom_data = {
        "bomFormat": "SPDX",  # Wrong format
        "specVersion": "1.6",
        "metadata": {"component": {"name": "test-component", "type": "library"}},
    }

    component = builder.get_component_metadata("test.json", sbom_data, "", "test-sbom-id")
    assert component is None


def test_get_component_metadata_missing_component():
    """Test get_component_metadata with missing component metadata."""
    builder = ProductSBOMBuilder()

    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {},  # Missing component
    }

    component = builder.get_component_metadata("test.json", sbom_data, "", "test-sbom-id")
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
def test_simple_external_reference_creation():
    """Test creating ExternalReference objects to isolate serialization issues."""

    import hashlib

    from sbomify.apps.sboms.sbom_format_schemas import cyclonedx_1_5 as cdx15
    from sbomify.apps.sboms.sbom_format_schemas import cyclonedx_1_6 as cdx16

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
@pytest.mark.skip(reason="Requires PostgreSQL - uses DISTINCT ON which is not supported by SQLite")
def test_product_sbom_file_generation(tmp_path):
    """Test that the product SBOM file is generated correctly with aggregated component data."""

    # Import necessary models
    from sbomify.apps.sboms.models import SBOM, Component, Product
    from sbomify.apps.sboms.utils import get_product_sbom_package
    from sbomify.apps.teams.models import Team

    # Create a team
    team = Team.objects.create(name="test-team", key="test-team")

    # Create a PUBLIC product with PUBLIC components attached directly
    product = Product.objects.create(name="test-product", team=team, is_public=True)

    # Create PUBLIC components
    component1 = Component.objects.create(
        name="component1", team=team, component_type="bom", visibility=Component.Visibility.PUBLIC
    )
    component2 = Component.objects.create(
        name="component2", team=team, component_type="bom", visibility=Component.Visibility.PUBLIC
    )

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

    # Attach components directly to product
    product.components.add(component1, component2)

    # Mock S3 client
    with patch("sbomify.apps.core.object_store.S3Client") as mock_s3:
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
        sbom_path = get_product_sbom_package(product, tmp_path, user=None)

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
@pytest.mark.skip(reason="Requires PostgreSQL - uses DISTINCT ON which is not supported by SQLite")
def test_sbom_vendor_and_remote_file_references(tmp_path):
    """Test that SBOMs use correct vendor 'sbomify, ltd' and remote file references."""

    import json

    from sbomify.apps.sboms.models import SBOM, Component, Product
    from sbomify.apps.sboms.utils import get_product_sbom_package
    from sbomify.apps.teams.models import Team

    # Create test entities
    team = Team.objects.create(name="test-team", key="test-team")
    product = Product.objects.create(name="test-product", team=team, is_public=True)

    # Create component
    component = Component.objects.create(
        name="test-component", team=team, component_type="bom", visibility=Component.Visibility.PUBLIC
    )

    # Create SBOM with specific filename
    sbom = SBOM.objects.create(
        name="test-sbom",
        component=component,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="my-component.cdx.json",
    )

    product.components.add(component)

    # Mock S3 client
    with patch("sbomify.apps.core.object_store.S3Client") as mock_s3:
        mock_s3_instance = mock_s3.return_value
        mock_s3_instance.get_sbom_data.return_value = json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "metadata": {"component": {"name": "test-comp", "type": "library", "version": "1.0.0"}},
            }
        ).encode()

        # Generate product SBOM
        sbom_path = get_product_sbom_package(product, tmp_path, user=None)

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

        expected_url = f"{settings.APP_BASE_URL}/api/v1/sboms/{sbom.uuid}/download"
        assert ext_ref["url"] == expected_url, f"Expected API URL but got '{ext_ref['url']}'"
        assert ext_ref["url"].startswith("http://"), f"External reference should be a URL: '{ext_ref['url']}'"
        assert ext_ref["type"] == "other"

        # TEST 3: Verify we only have the SBOM file, no ZIP
        assert sbom_path.name == "test-product.cdx.json", f"Expected SBOM file but got '{sbom_path.name}'"
        assert sbom_path.suffix == ".json", f"Expected JSON file but got '{sbom_path.suffix}'"


@pytest.mark.django_db
@pytest.mark.skip(reason="Requires PostgreSQL - uses DISTINCT ON which is not supported by SQLite")
def test_private_product_sbom_generation(tmp_path):
    """Test that private products can have SBOMs generated when called by authorized users."""

    from sbomify.apps.sboms.models import Product
    from sbomify.apps.sboms.utils import get_product_sbom_package
    from sbomify.apps.teams.models import Team

    # Create a team
    team = Team.objects.create(name="test-team", key="test-team")

    # Create a PRIVATE product
    private_product = Product.objects.create(name="private-product", team=team, is_public=False)

    # Should be able to generate SBOM for private product (authorization handled at API/view layer)
    sbom_path = get_product_sbom_package(private_product, tmp_path, user=None)

    # Verify the SBOM file was created
    assert sbom_path.exists(), "SBOM file should be created for private product"
    expected_name = "private-product.cdx.json"
    assert sbom_path.name == expected_name, f"Expected '{expected_name}' but got '{sbom_path.name}'"
    assert sbom_path.suffix == ".json", f"Expected JSON file but got '{sbom_path.suffix}'"


@pytest.mark.django_db
def test_invalid_sbom_id_validation():
    """Test that invalid SBOM IDs are handled gracefully."""

    from sbomify.apps.sboms.utils import validate_api_endpoint

    # Test with non-existent SBOM ID
    result = validate_api_endpoint("non-existent-sbom-id")
    assert result is False

    # Test with invalid UUID format
    result = validate_api_endpoint("invalid-uuid")
    assert result is False


@pytest.mark.django_db
def test_cyclonedx_schema_mapping_error():
    """Test that schema mapping errors are properly handled in CycloneDX Type3 enum."""
    from sbomify.apps.sboms.utils import _get_cyclonedx_type_for_product_link

    # This should NOT raise an AttributeError for releaseNotes
    # The schema uses snake_case (release_notes) not camelCase (releaseNotes)
    cyclonedx_type = _get_cyclonedx_type_for_product_link("release_notes")

    # Verify the type is returned correctly
    assert cyclonedx_type is not None

    # Test accessing the release_notes attribute (should work with snake_case)
    # This should work - snake_case format
    release_notes_type = cdx16.Type3.release_notes
    assert release_notes_type is not None

    # This should NOT work - camelCase format (the bug we had)
    try:
        # This should raise AttributeError
        camel_case_type = cdx16.Type3.releaseNotes
        # If we get here, the test fails because the bug is NOT fixed
        pytest.fail("Expected AttributeError for camelCase 'releaseNotes' but none was raised")
    except AttributeError:
        # This is expected - camelCase should not work
        pass


@pytest.mark.django_db
def test_product_external_references_schema_compatibility():
    """Test that product external references use correct schema format."""
    from sbomify.apps.sboms.models import Product, ProductLink
    from sbomify.apps.sboms.utils import create_product_external_references
    from sbomify.apps.teams.models import Team

    # Create test data
    team = Team.objects.create(name="test-team", key="test-team")
    product = Product.objects.create(name="test-product", team=team)

    # Create a product link that would trigger the schema error
    ProductLink.objects.create(
        product=product,
        link_type="release_notes",
        url="https://example.com/release-notes",
        title="Release Notes",
        description="Product release notes",
    )

    # This should not raise an AttributeError
    try:
        external_refs = create_product_external_references(product, user=None)

        # Verify we get a reference back
        assert len(external_refs) >= 1

        # Check the reference is properly formed
        release_notes_ref = external_refs[0]
        assert hasattr(release_notes_ref, "type")
        assert hasattr(release_notes_ref, "url")
        assert release_notes_ref.url == "https://example.com/release-notes"

    except AttributeError as e:
        if "releaseNotes" in str(e):
            pytest.fail(f"Schema mapping error not fixed: {e}")
        else:
            raise
    except ImportError:
        # Skip test if cyclonedx is not available
        pytest.skip("CycloneDX schema not available")


@pytest.mark.django_db
@pytest.mark.skip(reason="Requires PostgreSQL - uses DISTINCT ON which is not supported by SQLite")
def test_product_sbom_includes_documents_full_integration():
    """Test that documents are properly included in product SBOM generation with full data structure."""
    from sbomify.apps.core.models import Component
    from sbomify.apps.documents.models import Document
    from sbomify.apps.sboms.models import Product
    from sbomify.apps.sboms.utils import get_product_sbom_package
    from sbomify.apps.teams.models import Team

    # Create team
    team = Team.objects.create(name="test-team", key="test-team")

    # Create product
    product = Product.objects.create(name="test-product", team=team, is_public=True)

    # Create document component
    doc_component = Component.objects.create(
        name="Product Documentation", team=team, component_type="document", visibility=Component.Visibility.PUBLIC
    )

    # Attach component directly to product
    product.components.add(doc_component)

    # Create actual document
    document = Document.objects.create(
        name="Product Specification",
        component=doc_component,
        document_type="specification",
        description="Main product specification document",
        version="1.0",
    )

    # Test the external references function directly first
    from sbomify.apps.sboms.utils import create_product_external_references

    external_refs = create_product_external_references(product, user=None)

    # Should have at least one external reference for the document
    assert len(external_refs) >= 1, "Should have external references for documents"

    # Check if any reference is for our document
    doc_refs = [ref for ref in external_refs if hasattr(ref, "url") and "document" in ref.url]
    assert len(doc_refs) > 0, f"Should have document references. Got {len(external_refs)} total refs"

    # Test full SBOM generation
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        try:
            sbom_path = get_product_sbom_package(product, temp_path, user=None)

            # Read and parse the generated SBOM
            import json

            with open(sbom_path, "r") as f:
                sbom_data = json.loads(f.read())

            # Check that documents are in external references
            metadata = sbom_data.get("metadata", {})
            component = metadata.get("component", {})
            external_references = component.get("externalReferences", [])

            # Should have at least one external reference
            assert len(external_references) > 0, "SBOM should have external references"

            # Check for document reference
            doc_external_refs = [ref for ref in external_references if ref.get("type") == "documentation"]
            assert len(doc_external_refs) > 0, (
                f"Should have documentation external references. Got: {external_references}"
            )

            # Verify the document reference details
            doc_ref = doc_external_refs[0]
            assert "document" in doc_ref["url"], f"Document URL should contain 'document'. Got: {doc_ref['url']}"
            assert doc_ref.get("comment") == "Main product specification document"

        except ImportError:
            pytest.skip("CycloneDX schema not available")


@pytest.mark.django_db
def test_product_sbom_documents_relationship_debug():
    """Smoke test that product-attached document components surface in product external references."""
    from sbomify.apps.core.models import Component
    from sbomify.apps.documents.models import Document
    from sbomify.apps.sboms.models import Product
    from sbomify.apps.teams.models import Team

    # Create team
    team = Team.objects.create(name="debug-team", key="debug-team")

    # Create product
    product = Product.objects.create(name="debug-product", team=team, is_public=True)

    # Create document component
    doc_component = Component.objects.create(
        name="Debug Documentation", team=team, component_type="document", visibility=Component.Visibility.PUBLIC
    )

    # Attach component directly to product
    product.components.add(doc_component)

    # Create actual document
    Document.objects.create(
        name="Debug Specification",
        component=doc_component,
        document_type="specification",
        description="Debug specification document",
        version="1.0",
    )

    # Direct M2M query (current way)
    direct_query = Component.objects.filter(
        component_type="document",
        visibility=Component.Visibility.PUBLIC,
        products=product,
    ).distinct()

    # Verify the relationship resolves the document component
    assert direct_query.count() == 1, "Direct ProductComponent query should find the document component"
    assert doc_component in direct_query

    # Test external references
    from sbomify.apps.sboms.utils import create_product_external_references

    external_refs = create_product_external_references(product, user=None)

    assert len(external_refs) >= 1, "Should have external references"


@pytest.mark.django_db
@pytest.mark.skip(reason="Requires PostgreSQL - uses DISTINCT ON which is not supported by SQLite")
def test_sbom_serialization_uses_schema_alias(tmp_path):
    """
    Regression test: Verify SBOM serialization outputs '$schema' not 'field_schema'.

    The CycloneDX Pydantic model uses `field_schema` as the Python attribute name
    with `alias='$schema'`. When serializing to JSON, we must use `by_alias=True`
    to ensure the output contains '$schema' (valid CycloneDX) instead of 'field_schema'
    (invalid, causes validation errors when re-uploaded).
    """
    from sbomify.apps.sboms.models import SBOM, Component, Product
    from sbomify.apps.sboms.utils import get_product_sbom_package
    from sbomify.apps.teams.models import Team

    # Create test entities
    team = Team.objects.create(name="schema-test-team", key="schema-test-team")
    product = Product.objects.create(name="schema-test-product", team=team, is_public=True)

    component = Component.objects.create(
        name="schema-test-component", team=team, component_type="bom", visibility=Component.Visibility.PUBLIC
    )
    SBOM.objects.create(
        name="schema-test-sbom",
        component=component,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="schema-test.cdx.json",
    )
    product.components.add(component)

    with patch("sbomify.apps.core.object_store.S3Client") as mock_s3:
        mock_s3_instance = mock_s3.return_value
        mock_s3_instance.get_sbom_data.return_value = json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "metadata": {"component": {"name": "test", "type": "library", "version": "1.0.0"}},
            }
        ).encode()

        # Test product SBOM
        product_sbom_path = get_product_sbom_package(product, tmp_path)
        product_sbom_content = product_sbom_path.read_text()

        assert "field_schema" not in product_sbom_content, (
            "Product SBOM should not contain 'field_schema' - must use '$schema' alias"
        )
        if "$schema" in product_sbom_content:
            product_sbom_data = json.loads(product_sbom_content)
            assert "$schema" in product_sbom_data, "If schema is present, it must be '$schema'"


@pytest.mark.django_db
def test_populate_component_metadata_copies_authors_from_profile(
    sample_component,
    sample_user,
    sample_team_with_owner_member,  # noqa: F811
):
    """Test that authors are correctly copied from entity contacts with is_author=True."""
    from sbomify.apps.sboms.utils import populate_component_metadata_native_fields
    from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact

    # Create default profile with entity and contacts marked as authors
    profile = ContactProfile.objects.create(
        team=sample_component.team,
        name="Default Profile",
        is_default=True,
    )
    entity = ContactEntity.objects.create(
        profile=profile,
        name="Test Entity",
        email="entity@example.com",
        is_manufacturer=True,
        is_supplier=True,
    )
    # Create contacts with is_author=True
    author1 = ContactProfileContact.objects.create(
        entity=entity,
        name="Author One",
        email="author1@example.com",
        phone="123-456-7890",
        order=0,
        is_author=True,
    )
    author2 = ContactProfileContact.objects.create(
        entity=entity,
        name="Author Two",
        email="author2@example.com",
        phone="987-654-3210",
        order=1,
        is_author=True,
    )

    # Ensure component has no authors initially
    assert sample_component.authors.count() == 0

    # Populate metadata
    populate_component_metadata_native_fields(sample_component, sample_user)

    # Verify authors were copied from profile (contacts with is_author=True)
    assert sample_component.authors.count() == 2
    component_authors = list(sample_component.authors.order_by("order"))
    assert component_authors[0].name == author1.name
    assert component_authors[0].email == author1.email
    assert component_authors[0].phone == author1.phone
    assert component_authors[0].order == 0
    assert component_authors[1].name == author2.name
    assert component_authors[1].email == author2.email
    assert component_authors[1].phone == author2.phone
    assert component_authors[1].order == 1


@pytest.mark.django_db
def test_populate_component_metadata_replaces_existing_authors(
    sample_component,
    sample_user,
    sample_team_with_owner_member,  # noqa: F811
):
    """Test that existing component authors are replaced when profile has authors."""
    from sbomify.apps.sboms.models import ComponentAuthor
    from sbomify.apps.sboms.utils import populate_component_metadata_native_fields
    from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact

    # Create existing authors on component
    ComponentAuthor.objects.create(
        component=sample_component,
        name="Old Author",
        email="old@example.com",
        order=0,
    )
    assert sample_component.authors.count() == 1

    # Create default profile with entity and contact marked as author
    profile = ContactProfile.objects.create(
        team=sample_component.team,
        name="Default Profile",
        is_default=True,
    )
    entity = ContactEntity.objects.create(
        profile=profile,
        name="Test Entity",
        email="entity@example.com",
        is_manufacturer=True,
        is_supplier=True,
    )
    ContactProfileContact.objects.create(
        entity=entity,
        name="New Author",
        email="new@example.com",
        order=0,
        is_author=True,
    )

    # Populate metadata
    populate_component_metadata_native_fields(sample_component, sample_user)

    # Verify old authors were deleted and new ones created
    assert sample_component.authors.count() == 1
    assert sample_component.authors.first().name == "New Author"
    assert sample_component.authors.first().email == "new@example.com"


@pytest.mark.django_db
def test_populate_component_metadata_creates_user_author_when_no_profile_authors(
    sample_component,
    sample_user,
    sample_team_with_owner_member,  # noqa: F811
):
    """Test that user author is created as fallback only when no profile authors exist."""
    from sbomify.apps.sboms.utils import populate_component_metadata_native_fields
    from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact

    # Create default profile with entity but no contacts marked as author
    profile = ContactProfile.objects.create(
        team=sample_component.team,
        name="Default Profile",
        is_default=True,
    )
    entity = ContactEntity.objects.create(
        profile=profile,
        name="Test Entity",
        email="entity@example.com",
        is_manufacturer=True,
        is_supplier=True,
    )
    # Create a contact that is NOT an author
    ContactProfileContact.objects.create(
        entity=entity,
        name="Non-Author Contact",
        email="contact@example.com",
        is_author=False,
    )

    # Ensure user has name and email
    sample_user.first_name = "Test"
    sample_user.last_name = "User"
    sample_user.email = "testuser@example.com"
    sample_user.save()

    # Populate metadata
    populate_component_metadata_native_fields(sample_component, sample_user)

    # Verify user author was created as fallback (since no contacts have is_author=True)
    assert sample_component.authors.count() == 1
    author = sample_component.authors.first()
    assert author.name == "Test User"
    assert author.email == "testuser@example.com"


@pytest.mark.django_db
def test_populate_component_metadata_preserves_author_order(
    sample_component,
    sample_user,
    sample_team_with_owner_member,  # noqa: F811
):
    """Test that the order attribute is correctly set for authors copied from profile."""
    from sbomify.apps.sboms.utils import populate_component_metadata_native_fields
    from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact

    # Create default profile with entity and contacts marked as authors
    profile = ContactProfile.objects.create(
        team=sample_component.team,
        name="Default Profile",
        is_default=True,
    )
    entity = ContactEntity.objects.create(
        profile=profile,
        name="Test Entity",
        email="entity@example.com",
        is_manufacturer=True,
        is_supplier=True,
    )
    # Create author contacts in specific order
    author1 = ContactProfileContact.objects.create(
        entity=entity,
        name="First Author",
        email="first@example.com",
        order=0,
        is_author=True,
    )
    author2 = ContactProfileContact.objects.create(
        entity=entity,
        name="Second Author",
        email="second@example.com",
        order=1,
        is_author=True,
    )
    author3 = ContactProfileContact.objects.create(
        entity=entity,
        name="Third Author",
        email="third@example.com",
        order=2,
        is_author=True,
    )

    # Populate metadata
    populate_component_metadata_native_fields(sample_component, sample_user)

    # Verify authors are copied with correct order
    component_authors = list(sample_component.authors.order_by("order"))
    assert len(component_authors) == 3
    assert component_authors[0].order == 0
    assert component_authors[0].name == author1.name
    assert component_authors[1].order == 1
    assert component_authors[1].name == author2.name
    assert component_authors[2].order == 2
    assert component_authors[2].name == author3.name


# =============================================================================
# Issue #902: detect SBOMs generated by sbomify-action
# =============================================================================


@pytest.fixture
def clear_sbomify_action_cache():
    """Clear the per-SBOM detection cache between tests so a previous run's
    False result doesn't mask the current test's mocked SBOM content."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def _mock_sbom_content(mocker, content: dict) -> None:
    """Stand in for an S3 fetch: returns ``content`` JSON-encoded for the
    one call site that matters (``S3Client(...).get_sbom_data``)."""
    mock_client = mocker.MagicMock()
    mock_client.get_sbom_data.return_value = json.dumps(content).encode()
    mocker.patch("sbomify.apps.core.object_store.S3Client", return_value=mock_client)


@pytest.mark.django_db
class TestSbomWasGeneratedBySbomifyAction:
    """The CRA wizard suppresses its "use sbomify-action" CTA when the SBOM
    already came from that tool (issue #902). The detection must work
    across every CycloneDX shape that sbomify-action emits and the SPDX
    creators format it uses, and must fail safely on missing / corrupt
    blobs so the wizard never crashes on a bad upload."""

    def test_legacy_cyclonedx_1_4_tools_array(self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache):  # noqa: F811
        from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

        sample_sbom.format = "cyclonedx"
        sample_sbom.save(update_fields=["format"])
        _mock_sbom_content(
            mocker,
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.4",
                "metadata": {"tools": [{"vendor": "sbomify", "name": "sbomify-action", "version": "1.2.3"}]},
            },
        )

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is True

    def test_modern_cyclonedx_1_5_services(self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache):  # noqa: F811
        from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

        sample_sbom.format = "cyclonedx"
        sample_sbom.save(update_fields=["format"])
        _mock_sbom_content(
            mocker,
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "metadata": {
                    "tools": {
                        "components": [],
                        "services": [{"group": "sbomify", "name": "sbomify-action", "version": "1.2.3"}],
                    }
                },
            },
        )

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is True

    def test_modern_cyclonedx_with_space_separated_name(self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache):  # noqa: F811
        """augmentation.py historically shipped ``"sbomify action"`` (space)
        rather than ``"sbomify-action"``; both must still match so older
        SBOMs stay covered after the constant was renamed."""
        from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

        sample_sbom.format = "cyclonedx"
        sample_sbom.save(update_fields=["format"])
        _mock_sbom_content(
            mocker,
            {
                "specVersion": "1.6",
                "metadata": {"tools": {"components": [{"name": "sbomify action", "version": "0.9.0"}]}},
            },
        )

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is True

    def test_cyclonedx_without_sbomify_action(self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache):  # noqa: F811
        from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

        sample_sbom.format = "cyclonedx"
        sample_sbom.save(update_fields=["format"])
        _mock_sbom_content(
            mocker,
            {
                "specVersion": "1.6",
                "metadata": {"tools": [{"vendor": "Aquasecurity", "name": "trivy", "version": "0.50.0"}]},
            },
        )

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is False

    def test_spdx_creators_with_sbomify_action(self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache):  # noqa: F811
        from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

        sample_sbom.format = "spdx"
        sample_sbom.save(update_fields=["format"])
        _mock_sbom_content(
            mocker,
            {
                "spdxVersion": "SPDX-2.3",
                "creationInfo": {"creators": ["Tool: sbomify-action-1.2.3", "Organization: sbomify"]},
            },
        )

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is True

    @pytest.mark.parametrize(
        "creator",
        [
            "Tool: sbomify-action-1.2.3",  # plain semver, hyphen-joined name
            "Tool: sbomify action-1.2.3",  # legacy space-joined name
            "Tool: sbomify-action-1.2.3-rc1",  # pre-release suffix adds a hyphen
            "Tool: sbomify-action-2.0.0-alpha.1+build.7",  # SemVer pre-release + build
            "Tool: sbomify action-0.9.0-beta",  # legacy name + pre-release
        ],
    )
    def test_spdx_versioned_creator_matches(self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache, creator):  # noqa: F811
        """The SPDX creator format is ``Tool: <name>-<version>``. The
        version part can itself contain hyphens (``-rc1``, ``-alpha.1``)
        and ``+build`` metadata. The detector identifies the version
        suffix by an end-anchored SemVer-ish pattern starting from the
        rightmost hyphen, so the bare tool name is recovered exactly
        regardless of how many hyphens the version contains."""
        from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

        sample_sbom.format = "spdx"
        sample_sbom.save(update_fields=["format"])
        _mock_sbom_content(
            mocker,
            {"spdxVersion": "SPDX-2.3", "creationInfo": {"creators": [creator]}},
        )

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is True

    def test_spdx_creators_without_sbomify_action(self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache):  # noqa: F811
        from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

        sample_sbom.format = "spdx"
        sample_sbom.save(update_fields=["format"])
        _mock_sbom_content(mocker, {"spdxVersion": "SPDX-2.3", "creationInfo": {"creators": ["Tool: trivy-0.50.0"]}})

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is False

    def test_missing_filename_fails_safe(self, sample_sbom: SBOM, clear_sbomify_action_cache):  # noqa: F811
        from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

        sample_sbom.sbom_filename = ""
        sample_sbom.save(update_fields=["sbom_filename"])

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is False

    def test_s3_fetch_failure_fails_safe(self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache):  # noqa: F811
        """A missing or corrupt blob must not crash the wizard. The CTA
        gate is a UX nicety, not a correctness boundary — fail-safe to
        the existing behaviour (CTA shown) instead of propagating."""
        from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

        mock_client = mocker.MagicMock()
        mock_client.get_sbom_data.side_effect = RuntimeError("S3 boom")
        mocker.patch("sbomify.apps.core.object_store.S3Client", return_value=mock_client)

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is False

    def test_result_is_cached_per_sbom(self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache):  # noqa: F811
        """Detection is meant to be free on the hot path; the second call
        for the same SBOM must not re-fetch from S3."""
        from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

        sample_sbom.format = "cyclonedx"
        sample_sbom.save(update_fields=["format"])
        mock_client = mocker.MagicMock()
        mock_client.get_sbom_data.return_value = json.dumps(
            {"specVersion": "1.6", "metadata": {"tools": {"components": [{"name": "sbomify-action"}]}}}
        ).encode()
        mocker.patch("sbomify.apps.core.object_store.S3Client", return_value=mock_client)

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is True
        assert sbom_was_generated_by_sbomify_action(sample_sbom) is True
        assert mock_client.get_sbom_data.call_count == 1

    def test_transient_fetch_failure_uses_short_negative_ttl(
        self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache
    ):  # noqa: F811
        """A failed S3 read must NOT be cached for the full 24h positive
        TTL; otherwise a brief storage hiccup keeps the CTA on for the rest
        of the day for SBOMs that would be detected once storage recovers."""
        from sbomify.apps.sboms.utils import (
            _SBOMIFY_ACTION_CHECK_CACHE_TTL,
            _SBOMIFY_ACTION_NEGATIVE_CACHE_TTL,
            sbom_was_generated_by_sbomify_action,
        )

        cache_set = mocker.patch("django.core.cache.cache.set")
        mocker.patch("django.core.cache.cache.get", return_value=None)
        mock_client = mocker.MagicMock()
        mock_client.get_sbom_data.side_effect = RuntimeError("S3 down")
        mocker.patch("sbomify.apps.core.object_store.S3Client", return_value=mock_client)

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is False

        assert cache_set.called, "result must still be cached, just briefly"
        ttl_used = cache_set.call_args.args[2]
        assert ttl_used == _SBOMIFY_ACTION_NEGATIVE_CACHE_TTL
        assert ttl_used < _SBOMIFY_ACTION_CHECK_CACHE_TTL

    def test_definitive_result_uses_long_positive_ttl(self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache):  # noqa: F811
        """A successfully parsed SBOM is immutable; the answer should stick
        for the full 24h."""
        from sbomify.apps.sboms.utils import (
            _SBOMIFY_ACTION_CHECK_CACHE_TTL,
            sbom_was_generated_by_sbomify_action,
        )

        sample_sbom.format = "cyclonedx"
        sample_sbom.save(update_fields=["format"])
        _mock_sbom_content(
            mocker,
            {"specVersion": "1.6", "metadata": {"tools": [{"name": "sbomify-action"}]}},
        )
        cache_set = mocker.patch("django.core.cache.cache.set")
        mocker.patch("django.core.cache.cache.get", return_value=None)

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is True

        assert cache_set.called
        ttl_used = cache_set.call_args.args[2]
        assert ttl_used == _SBOMIFY_ACTION_CHECK_CACHE_TTL

    def test_cache_get_failure_treated_as_miss(self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache):  # noqa: F811
        """django-redis without IGNORE_EXCEPTIONS raises on Redis outage.
        cache.get() failure must NOT propagate — Step 2 must keep rendering."""
        from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

        sample_sbom.format = "cyclonedx"
        sample_sbom.save(update_fields=["format"])
        mocker.patch("django.core.cache.cache.get", side_effect=ConnectionError("Redis down"))
        mocker.patch("django.core.cache.cache.set", side_effect=ConnectionError("Redis down"))
        _mock_sbom_content(
            mocker,
            {"specVersion": "1.6", "metadata": {"tools": [{"name": "sbomify-action"}]}},
        )

        # Without the wrapper this would raise ConnectionError out into the
        # wizard render; with it, the S3 path still runs and returns True.
        assert sbom_was_generated_by_sbomify_action(sample_sbom) is True

    def test_cache_set_failure_does_not_propagate(self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache):  # noqa: F811
        """If cache.set raises (Redis dropped between get and set), the
        computed result must still be returned to the caller."""
        from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

        sample_sbom.format = "cyclonedx"
        sample_sbom.save(update_fields=["format"])
        mocker.patch("django.core.cache.cache.get", return_value=None)
        mocker.patch("django.core.cache.cache.set", side_effect=ConnectionError("Redis down"))
        _mock_sbom_content(
            mocker,
            {"specVersion": "1.6", "metadata": {"tools": [{"name": "trivy"}]}},
        )

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is False

    @pytest.mark.parametrize(
        "fmt,payload",
        [
            # CycloneDX guards — these must actually flow through
            # _cyclonedx_metadata_has_sbomify_action, not the SPDX branch.
            ("cyclonedx", ["not", "a", "dict"]),  # top-level list instead of object
            ("cyclonedx", {"metadata": "not-a-dict"}),  # scalar metadata
            ("cyclonedx", {"metadata": {"tools": "not-a-list-or-dict"}}),  # scalar tools
            ("cyclonedx", {"metadata": {"tools": [None, 1, "x"]}}),  # malformed legacy entries
            (
                "cyclonedx",
                {"metadata": {"tools": {"components": [None, 1, "x"], "services": None}}},
            ),  # malformed modern shape
            # SPDX guards — must flow through _spdx_metadata_has_sbomify_action.
            ("spdx", ["not", "a", "dict"]),
            ("spdx", {"creationInfo": "not-a-dict"}),
            ("spdx", {"creationInfo": {"creators": "not-a-list"}}),
            ("spdx", {"creationInfo": {"creators": [123, None]}}),  # non-string creators
        ],
    )
    def test_malformed_shapes_fail_safe(self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache, fmt, payload):  # noqa: F811
        """A valid-JSON-but-wrong-shape blob must not raise out of the
        detector — Step 2 status rendering relies on this falling safe.
        Each parametrised case sets ``sample_sbom.format`` so the malformed
        shape flows through the parser it is meant to exercise rather than
        being short-circuited by the wrong-format branch."""
        from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

        sample_sbom.format = fmt
        sample_sbom.save(update_fields=["format"])
        _mock_sbom_content(mocker, payload)

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is False

    @pytest.mark.parametrize(
        "tool_name",
        [
            "sbomify-action-wrapper",  # different tool name; no version
            "sbomify-action-wrapper-1.0.0",  # different tool name + version
            "sbomify-action-extras-2.3.4-rc1",  # different tool name + SemVer pre-release
            "not-sbomify-action-1.0.0",  # prefix-like string that contains "sbomify-action"
            # A version-like fragment inside the tool name (``v2``) must not
            # split the name early. Without the SemVer-ish MAJOR.MINOR
            # requirement on the version suffix,
            # ``sbomify-action-v2-wrapper-1.0.0`` would split at ``-v2-`` and
            # false-positive as sbomify-action.
            "sbomify-action-v2-wrapper-1.0.0",
            "sbomify-action-v3-fork-2.0.0-rc1",
        ],
    )
    def test_spdx_does_not_over_match_similar_names(
        self, mocker, sample_sbom: SBOM, clear_sbomify_action_cache, tool_name
    ):  # noqa: F811
        """A tool whose name only contains ``sbomify-action`` as a substring
        must not be reported as sbomify-action. The version-aware split
        anchors on a real ``MAJOR.MINOR`` suffix scanned from the right,
        so wrapper/fork names that embed ``v2`` or similar fragments stay
        attached to the name rather than getting peeled off."""
        from sbomify.apps.sboms.utils import sbom_was_generated_by_sbomify_action

        sample_sbom.format = "spdx"
        sample_sbom.save(update_fields=["format"])
        _mock_sbom_content(
            mocker,
            {"spdxVersion": "SPDX-2.3", "creationInfo": {"creators": [f"Tool: {tool_name}"]}},
        )

        assert sbom_was_generated_by_sbomify_action(sample_sbom) is False

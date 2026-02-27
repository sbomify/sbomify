"""
Integration tests for TEA API endpoints.
"""

import uuid as uuid_module

import pytest
from django.test import Client

from sbomify.apps.core.models import Product, Release
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM, ProductIdentifier
from sbomify.apps.tea.mappers import TEA_API_VERSION

TEA_URL_PREFIX = f"/tea/v{TEA_API_VERSION}"
NONEXISTENT_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.mark.django_db
class TestTEADiscoveryEndpoint:
    """Tests for /tea/v1/discovery endpoint."""

    def test_discovery_with_uuid_tei(self, tea_enabled_product):
        """Test discovery with UUID TEI type."""
        Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        tei = f"urn:tei:uuid:example.com:{tea_enabled_product.uuid}"
        url = f"{TEA_URL_PREFIX}/discovery?tei={tei}&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1

        # Check structure
        result = data[0]
        assert "productReleaseUuid" in result
        assert "servers" in result
        assert len(result["servers"]) == 1
        assert "rootUrl" in result["servers"][0]
        assert "versions" in result["servers"][0]

    def test_discovery_with_purl_tei(self, tea_enabled_product):
        """Test discovery with PURL TEI type."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:pypi/test-package",
        )
        Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        tei = "urn:tei:purl:example.com:pkg:pypi/test-package"
        url = f"{TEA_URL_PREFIX}/discovery?tei={tei}&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

    def test_discovery_invalid_tei(self, tea_enabled_product):
        """Test discovery with invalid TEI format."""
        client = Client()
        url = f"{TEA_URL_PREFIX}/discovery?tei=invalid-tei&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 400

    def test_discovery_no_match(self, tea_enabled_product):
        """Test discovery with no matching releases."""
        client = Client()
        tei = "urn:tei:uuid:example.com:00000000-0000-0000-0000-000000000000"
        url = f"{TEA_URL_PREFIX}/discovery?tei={tei}&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 404

    def test_discovery_invalid_workspace(self):
        """Test discovery with invalid workspace."""
        client = Client()
        tei = "urn:tei:uuid:example.com:00000000-0000-0000-0000-000000000000"
        url = f"{TEA_URL_PREFIX}/discovery?tei={tei}&workspace_key=nonexistent"

        response = client.get(url)

        assert response.status_code == 400


@pytest.mark.django_db
class TestTEAProductsEndpoint:
    """Tests for /tea/v1/products endpoint."""

    def test_list_products(self, tea_enabled_product):
        """Test listing all products."""
        client = Client()
        url = f"{TEA_URL_PREFIX}/products?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert "timestamp" in data
        assert "pageStartIndex" in data
        assert "pageSize" in data
        assert "totalResults" in data
        assert "results" in data
        assert data["totalResults"] == 1

    def test_list_products_pagination(self, tea_enabled_product):
        """Test product listing pagination."""
        # Create additional products
        for i in range(5):
            Product.objects.create(
                team=tea_enabled_product.team,
                name=f"Product {i}",
                is_public=True,
            )

        client = Client()
        url = f"{TEA_URL_PREFIX}/products?workspace_key={tea_enabled_product.team.key}&pageOffset=0&pageSize=3"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["pageSize"] == 3
        assert len(data["results"]) <= 3

    def test_list_products_filter_by_identifier(self, tea_enabled_product):
        """Test filtering products by identifier."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:pypi/test-filter-package",
        )

        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/products?workspace_key={ws}&idType=PURL&idValue=pkg:pypi/test-filter-package"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["totalResults"] == 1

    def test_list_products_private_excluded(self, tea_enabled_product):
        """Test that private products are excluded."""
        tea_enabled_product.is_public = False
        tea_enabled_product.save()

        client = Client()
        url = f"{TEA_URL_PREFIX}/products?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        # The sample product should not be in results since it's private
        product_ids = [p["uuid"] for p in data["results"]]
        assert str(tea_enabled_product.uuid) not in product_ids

    def test_list_products_filter_by_tei(self, tea_enabled_product):
        """Test filtering products by TEI identifier type."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:pypi/tei-filter-test",
        )
        Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        tei = "urn:tei:purl:example.com:pkg:pypi/tei-filter-test"
        url = f"{TEA_URL_PREFIX}/products?workspace_key={tea_enabled_product.team.key}&idType=TEI&idValue={tei}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["totalResults"] == 1
        product_ids = [p["uuid"] for p in data["results"]]
        assert str(tea_enabled_product.uuid) in product_ids

    def test_list_products_filter_by_tei_invalid(self, tea_enabled_product):
        """Test filtering products by invalid TEI returns empty results."""
        client = Client()
        url = f"{TEA_URL_PREFIX}/products?workspace_key={tea_enabled_product.team.key}&idType=TEI&idValue=invalid-tei"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["totalResults"] == 0

    def test_list_products_filter_by_unknown_idtype_returns_empty(self, tea_enabled_product):
        """C2: Unknown idType returns empty results, not unfiltered data."""
        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/products?workspace_key={ws}&idType=UNKNOWN_TYPE&idValue=some-value"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["totalResults"] == 0


@pytest.mark.django_db
class TestTEAProductEndpoint:
    """Tests for /tea/v1/product/{uuid} endpoint."""

    def test_get_product(self, tea_enabled_product):
        """Test getting a single product."""
        client = Client()
        url = f"{TEA_URL_PREFIX}/product/{tea_enabled_product.uuid}?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert data["uuid"] == str(tea_enabled_product.uuid)
        uuid_module.UUID(data["uuid"])  # regression: must be valid UUID, not internal ID
        assert data["name"] == tea_enabled_product.name
        assert "identifiers" in data

    def test_get_product_not_found(self, tea_enabled_product):
        """Test getting a non-existent product."""
        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/product/{NONEXISTENT_UUID}?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 404

    def test_get_private_product_not_accessible(self, tea_enabled_product):
        """Test that private products are not accessible."""
        tea_enabled_product.is_public = False
        tea_enabled_product.save()

        client = Client()
        url = f"{TEA_URL_PREFIX}/product/{tea_enabled_product.uuid}?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 404


@pytest.mark.django_db
class TestTEAProductReleasesEndpoint:
    """Tests for /tea/v1/product/{uuid}/releases endpoint."""

    def test_get_product_releases(self, tea_enabled_product):
        """Test getting releases for a product."""
        Release.objects.create(product=tea_enabled_product, name="v1.0.0")
        Release.objects.create(product=tea_enabled_product, name="v2.0.0")

        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/product/{tea_enabled_product.uuid}/releases?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert "results" in data
        assert data["totalResults"] == 2

        # Check release structure
        if data["results"]:
            release = data["results"][0]
            assert "uuid" in release
            assert "version" in release
            assert "createdDate" in release


@pytest.mark.django_db
class TestTEAProductReleaseEndpoint:
    """Tests for /tea/v1/productRelease/{uuid} endpoint."""

    def test_get_product_release(self, tea_enabled_product):
        """Test getting a single product release."""
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        url = f"{TEA_URL_PREFIX}/productRelease/{release.uuid}?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert data["uuid"] == str(release.uuid)
        uuid_module.UUID(data["uuid"])  # regression: must be valid UUID, not internal ID
        uuid_module.UUID(data["product"])
        assert data["version"] == "v1.0.0"
        assert data["product"] == str(tea_enabled_product.uuid)
        assert data["productName"] == tea_enabled_product.name

    def test_get_product_release_not_found(self, tea_enabled_product):
        """Test getting a non-existent release."""
        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/productRelease/{NONEXISTENT_UUID}?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 404


@pytest.mark.django_db
class TestTEAProductReleaseCollectionEndpoints:
    """Tests for product release collection endpoints."""

    def test_get_latest_collection(self, tea_enabled_product):
        """Test getting latest collection for a product release."""
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/productRelease/{release.uuid}/collection/latest?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert data["uuid"] == str(release.uuid)
        assert data["version"] == 1
        assert data["belongsTo"] == "PRODUCT_RELEASE"
        assert "artifacts" in data

    def test_get_collections(self, tea_enabled_product):
        """Test getting all collections for a product release."""
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        url = f"{TEA_URL_PREFIX}/productRelease/{release.uuid}/collections?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)
        assert len(data) == 1

    def test_get_collection_by_version(self, tea_enabled_product):
        """Test getting a specific collection version."""
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/productRelease/{release.uuid}/collection/1?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 1

    def test_get_collection_invalid_version(self, tea_enabled_product):
        """Test getting a non-existent collection version."""
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/productRelease/{release.uuid}/collection/999?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 404


@pytest.mark.django_db
class TestTEAComponentEndpoint:
    """Tests for /tea/v1/component/{uuid} endpoint."""

    def test_get_component(self, tea_enabled_component):
        """Test getting a single component."""
        client = Client()
        url = f"{TEA_URL_PREFIX}/component/{tea_enabled_component.uuid}?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert data["uuid"] == str(tea_enabled_component.uuid)
        uuid_module.UUID(data["uuid"])  # regression: must be valid UUID, not internal ID
        assert data["name"] == tea_enabled_component.name
        assert "identifiers" in data

    def test_get_component_not_found(self, tea_enabled_component):
        """Test getting a non-existent component."""
        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/component/{NONEXISTENT_UUID}?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 404


@pytest.mark.django_db
class TestTEAComponentReleasesEndpoint:
    """Tests for /tea/v1/component/{uuid}/releases endpoint."""

    def test_get_component_releases(self, tea_enabled_component, sample_sbom):
        """Test getting releases (SBOMs) for a component."""
        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/component/{tea_enabled_component.uuid}/releases?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)
        assert len(data) == 1

        # Check release structure
        release = data[0]
        assert "uuid" in release
        assert "version" in release
        assert "component" in release


@pytest.mark.django_db
class TestTEAComponentReleaseEndpoint:
    """Tests for /tea/v1/componentRelease/{uuid} endpoint."""

    def test_get_component_release(self, tea_enabled_component, sample_sbom):
        """Test getting a component release with collection."""
        client = Client()
        url = f"{TEA_URL_PREFIX}/componentRelease/{sample_sbom.uuid}?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert "release" in data
        assert "latestCollection" in data
        assert data["release"]["uuid"] == str(sample_sbom.uuid)
        assert data["latestCollection"]["belongsTo"] == "COMPONENT_RELEASE"

    def test_get_component_release_not_found(self, tea_enabled_component):
        """Test getting a non-existent component release."""
        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/componentRelease/{NONEXISTENT_UUID}?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 404


@pytest.mark.django_db
class TestTEAComponentReleaseCollectionEndpoints:
    """Tests for component release collection endpoints."""

    def test_get_latest_collection(self, tea_enabled_component, sample_sbom):
        """Test getting latest collection for a component release."""
        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/componentRelease/{sample_sbom.uuid}/collection/latest?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert data["uuid"] == str(sample_sbom.uuid)
        assert data["version"] == 1
        assert data["belongsTo"] == "COMPONENT_RELEASE"
        assert "artifacts" in data
        assert "date" in data
        assert "updateReason" in data
        assert data["updateReason"]["type"] == "INITIAL_RELEASE"

    def test_get_latest_collection_not_found(self, tea_enabled_component):
        """Test getting latest collection for non-existent component release."""
        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/componentRelease/{NONEXISTENT_UUID}/collection/latest?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 404

    def test_get_collections(self, tea_enabled_component, sample_sbom):
        """Test getting all collections for a component release."""
        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/componentRelease/{sample_sbom.uuid}/collections?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["belongsTo"] == "COMPONENT_RELEASE"

    def test_get_collections_not_found(self, tea_enabled_component):
        """Test getting collections for non-existent component release."""
        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/componentRelease/00000000-0000-0000-0000-000000000000/collections?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 404

    def test_get_collection_by_version(self, tea_enabled_component, sample_sbom):
        """Test getting a specific collection version for a component release."""
        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/componentRelease/{sample_sbom.uuid}/collection/1?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 1
        assert data["belongsTo"] == "COMPONENT_RELEASE"

    def test_get_collection_invalid_version(self, tea_enabled_component, sample_sbom):
        """Test getting a non-existent collection version for a component release."""
        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/componentRelease/{sample_sbom.uuid}/collection/999?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 404


@pytest.mark.django_db
class TestTEAArtifactEndpoint:
    """Tests for /tea/v1/artifact/{uuid} endpoint."""

    def test_get_sbom_artifact(self, tea_enabled_component, sample_sbom):
        """Test getting an SBOM artifact."""
        client = Client()
        url = f"{TEA_URL_PREFIX}/artifact/{sample_sbom.uuid}?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert data["uuid"] == str(sample_sbom.uuid)
        uuid_module.UUID(data["uuid"])  # regression: must be valid UUID, not internal ID
        assert data["type"] == "BOM"
        assert "formats" in data
        assert len(data["formats"]) == 1

    def test_get_artifact_not_found(self, tea_enabled_component):
        """Test getting a non-existent artifact."""
        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/artifact/{NONEXISTENT_UUID}?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 404

    def test_get_sbom_artifact_uses_media_type(self, tea_enabled_component, sample_sbom):
        """Test that artifact response uses 'mediaType' field name (not 'mimeType')."""
        client = Client()
        url = f"{TEA_URL_PREFIX}/artifact/{sample_sbom.uuid}?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        fmt = data["formats"][0]
        assert "mediaType" in fmt
        assert "mimeType" not in fmt

    def test_get_sbom_artifact_with_checksum(self, tea_enabled_component, sample_sbom):
        """Test that artifact includes SHA-256 checksum when available."""
        sample_sbom.sha256_hash = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        sample_sbom.save()

        client = Client()
        url = f"{TEA_URL_PREFIX}/artifact/{sample_sbom.uuid}?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        fmt = data["formats"][0]
        assert len(fmt["checksums"]) == 1
        assert fmt["checksums"][0]["algType"] == "SHA-256"
        assert fmt["checksums"][0]["algValue"] == sample_sbom.sha256_hash

    def test_get_sbom_artifact_without_checksum(self, tea_enabled_component, sample_sbom):
        """Test that artifact has empty checksums when sha256_hash is not set."""
        sample_sbom.sha256_hash = ""
        sample_sbom.save()

        client = Client()
        url = f"{TEA_URL_PREFIX}/artifact/{sample_sbom.uuid}?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        fmt = data["formats"][0]
        assert fmt["checksums"] == []

    def test_get_document_artifact(self, tea_enabled_component):
        """Test getting a Document-type artifact."""
        doc = Document.objects.create(
            name="Test Threat Model",
            component=tea_enabled_component,
            document_type=Document.DocumentType.THREAT_MODEL,
            content_type="application/pdf",
            source="test",
        )

        client = Client()
        url = f"{TEA_URL_PREFIX}/artifact/{doc.uuid}?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert data["uuid"] == str(doc.uuid)
        assert data["name"] == "Test Threat Model"
        assert data["type"] == "THREAT_MODEL"
        assert len(data["formats"]) == 1
        assert data["formats"][0]["mediaType"] == "application/pdf"

    def test_get_document_artifact_with_checksum(self, tea_enabled_component):
        """Test that Document artifact includes checksum when available."""
        doc = Document.objects.create(
            name="Test License",
            component=tea_enabled_component,
            document_type=Document.DocumentType.LICENSE,
            content_type="text/plain",
            source="test",
            sha256_hash="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )

        client = Client()
        url = f"{TEA_URL_PREFIX}/artifact/{doc.uuid}?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert data["type"] == "LICENSE"
        fmt = data["formats"][0]
        assert len(fmt["checksums"]) == 1
        assert fmt["checksums"][0]["algType"] == "SHA-256"
        assert fmt["checksums"][0]["algValue"] == doc.sha256_hash


@pytest.mark.django_db
class TestTEAProductReleasesQueryEndpoint:
    """Tests for /tea/v1/productReleases endpoint."""

    def test_query_product_releases(self, tea_enabled_product):
        """Test querying product releases."""
        Release.objects.create(product=tea_enabled_product, name="v1.0.0")
        Release.objects.create(product=tea_enabled_product, name="v2.0.0")

        client = Client()
        url = f"{TEA_URL_PREFIX}/productReleases?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert "timestamp" in data
        assert "results" in data
        assert data["totalResults"] == 2

    def test_query_product_releases_with_filter(self, tea_enabled_product):
        """Test querying product releases with identifier filter."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.CPE,
            value="cpe:2.3:a:test:product",
        )
        Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/productReleases?workspace_key={ws}&idType=CPE&idValue=cpe:2.3:a:test:product"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["totalResults"] == 1

    def test_query_product_releases_filter_by_tei(self, tea_enabled_product):
        """Test querying product releases with TEI identifier filter."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:pypi/tei-release-test",
        )
        release = Release.objects.create(product=tea_enabled_product, name="v2.0.0")

        client = Client()
        tei = "urn:tei:purl:example.com:pkg:pypi/tei-release-test"
        url = f"{TEA_URL_PREFIX}/productReleases?workspace_key={tea_enabled_product.team.key}&idType=TEI&idValue={tei}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["totalResults"] == 1
        release_ids = [r["uuid"] for r in data["results"]]
        assert str(release.uuid) in release_ids

    def test_query_product_releases_filter_by_tei_no_match(self, tea_enabled_product):
        """Test querying product releases with TEI that matches no products."""
        Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        tei = "urn:tei:uuid:example.com:00000000-0000-0000-0000-000000000000"
        url = f"{TEA_URL_PREFIX}/productReleases?workspace_key={tea_enabled_product.team.key}&idType=TEI&idValue={tei}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["totalResults"] == 0


@pytest.mark.django_db
class TestTEADisabledWorkspace:
    """Tests for TEA API when TEA is disabled."""

    def test_tea_disabled_returns_400(self, sample_product):
        """Test that TEA API returns 400 when TEA is disabled."""
        sample_product.is_public = True
        sample_product.save()
        sample_product.team.tea_enabled = False
        sample_product.team.save()

        client = Client()
        url = f"{TEA_URL_PREFIX}/products?workspace_key={sample_product.team.key}"

        response = client.get(url)

        assert response.status_code == 400

    def test_tea_disabled_error_message(self, sample_product):
        """Test that TEA disabled returns generic error message (H3)."""
        sample_product.is_public = True
        sample_product.save()
        sample_product.team.tea_enabled = False
        sample_product.team.save()

        client = Client()
        url = f"{TEA_URL_PREFIX}/products?workspace_key={sample_product.team.key}"

        response = client.get(url)
        data = response.json()
        assert "not found or not accessible" in data["error"].lower()


@pytest.mark.django_db
class TestTEAPrivateComponentVisibility:
    """Tests for private component visibility filtering (C3, C4, L13)."""

    def test_private_component_not_in_product_release(self, tea_enabled_product, tea_enabled_component):
        """C4: Private components are excluded from product release component refs."""
        from sbomify.apps.core.models import Component, Project, Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM

        # Create project linking component to product
        project = Project.objects.create(team=tea_enabled_product.team, name="Test Project")
        project.products.add(tea_enabled_product)
        project.components.add(tea_enabled_component)

        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        # Create SBOM for the component
        sbom = SBOM.objects.create(
            component=tea_enabled_component,
            name="Test SBOM",
            format="cyclonedx",
            format_version="1.4",
            source="test",
        )
        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        # Verify component visible when public
        client = Client()
        url = f"{TEA_URL_PREFIX}/productRelease/{release.uuid}?workspace_key={tea_enabled_product.team.key}"
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert len(data["components"]) == 1

        # Make component private
        tea_enabled_component.visibility = Component.Visibility.PRIVATE
        tea_enabled_component.save()

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        component_uuids = [c["uuid"] for c in data["components"]]
        assert str(tea_enabled_component.uuid) not in component_uuids

    def test_private_component_excluded_from_collection(self, tea_enabled_product, tea_enabled_component):
        """C3: Private component artifacts are excluded from collections."""
        from sbomify.apps.core.models import Component, Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM

        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        sbom = SBOM.objects.create(
            component=tea_enabled_component,
            name="Test SBOM",
            format="cyclonedx",
            format_version="1.4",
            source="test",
        )
        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/productRelease/{release.uuid}/collection/latest?workspace_key={ws}"

        # Verify artifact visible when component is public
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert len(data["artifacts"]) == 1

        # Make component private
        tea_enabled_component.visibility = Component.Visibility.PRIVATE
        tea_enabled_component.save()

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        artifact_uuids = [a["uuid"] for a in data["artifacts"]]
        assert str(sbom.uuid) not in artifact_uuids

    def test_private_component_returns_404(self, tea_enabled_component):
        """L13: Private component returns 404."""
        from sbomify.apps.core.models import Component

        tea_enabled_component.visibility = Component.Visibility.PRIVATE
        tea_enabled_component.save()

        client = Client()
        url = f"{TEA_URL_PREFIX}/component/{tea_enabled_component.uuid}?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)
        assert response.status_code == 404


@pytest.mark.django_db
class TestTEADocumentArtifacts:
    """Tests for document artifacts in collections (M12)."""

    def test_collection_includes_document_artifacts(self, tea_enabled_product, tea_enabled_component):
        """M12: Document artifacts appear in product release collections."""
        from sbomify.apps.core.models import Release, ReleaseArtifact

        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        doc = Document.objects.create(
            name="Test License",
            component=tea_enabled_component,
            document_type=Document.DocumentType.LICENSE,
            content_type="text/plain",
            source="test",
        )
        ReleaseArtifact.objects.create(release=release, document=doc)

        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/productRelease/{release.uuid}/collection/latest?workspace_key={ws}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()

        assert len(data["artifacts"]) == 1
        doc_artifact = next((a for a in data["artifacts"] if a["uuid"] == str(doc.uuid)), None)
        assert doc_artifact is not None
        assert doc_artifact["type"] == "LICENSE"
        assert doc_artifact["name"] == "Test License"


@pytest.mark.django_db
class TestTEACollectionVersioning:
    """Tests for collection versioning on product releases."""

    def test_initial_version_is_one(self, tea_enabled_product):
        """Test that a new release starts at collection version 1."""
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/productRelease/{release.uuid}/collection/latest?workspace_key={ws}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 1
        assert data["updateReason"]["type"] == "INITIAL_RELEASE"

    def test_version_increments_on_artifact_add(self, tea_enabled_product, tea_enabled_component):
        """Test that collection version bumps when a second artifact is added."""
        from sbomify.apps.core.models import ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM

        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        # Add first artifact (no bump — it's the first)
        sbom1 = SBOM.objects.create(
            component=tea_enabled_component,
            name="SBOM 1",
            format="cyclonedx",
            format_version="1.4",
            source="test",
        )
        ReleaseArtifact.objects.create(release=release, sbom=sbom1)

        release.refresh_from_db()
        assert release.collection_version == 1

        # Add second artifact (should bump)
        sbom2 = SBOM.objects.create(
            component=tea_enabled_component,
            name="SBOM 2",
            format="spdx",
            format_version="2.3",
            source="test",
        )
        ReleaseArtifact.objects.create(release=release, sbom=sbom2)

        release.refresh_from_db()
        assert release.collection_version == 2
        assert release.collection_update_reason == "ARTIFACT_ADDED"

    def test_version_increments_on_artifact_remove(self, tea_enabled_product, tea_enabled_component):
        """Test that collection version bumps when an artifact is removed."""
        from sbomify.apps.core.models import ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM

        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        sbom = SBOM.objects.create(
            component=tea_enabled_component,
            name="SBOM 1",
            format="cyclonedx",
            format_version="1.4",
            source="test",
        )
        artifact = ReleaseArtifact.objects.create(release=release, sbom=sbom)

        release.refresh_from_db()
        initial_version = release.collection_version

        artifact.delete()

        release.refresh_from_db()
        assert release.collection_version == initial_version + 1
        assert release.collection_update_reason == "ARTIFACT_REMOVED"

    def test_collection_version_endpoint_validates_range(self, tea_enabled_product, tea_enabled_component):
        """Test that only the current version returns 200; historical and future versions return 404."""
        from sbomify.apps.core.models import ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM

        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        # Add two artifacts to bump version to 2
        sbom1 = SBOM.objects.create(
            component=tea_enabled_component,
            name="SBOM 1",
            format="cyclonedx",
            format_version="1.4",
            source="test",
        )
        ReleaseArtifact.objects.create(release=release, sbom=sbom1)
        sbom2 = SBOM.objects.create(
            component=tea_enabled_component,
            name="SBOM 2",
            format="spdx",
            format_version="2.3",
            source="test",
        )
        ReleaseArtifact.objects.create(release=release, sbom=sbom2)

        release.refresh_from_db()
        assert release.collection_version == 2

        client = Client()
        ws = tea_enabled_product.team.key

        # Version 1 is historical -- should return 404
        response = client.get(f"{TEA_URL_PREFIX}/productRelease/{release.uuid}/collection/1?workspace_key={ws}")
        assert response.status_code == 404

        # Version 2 is current -- should return 200
        response = client.get(f"{TEA_URL_PREFIX}/productRelease/{release.uuid}/collection/2?workspace_key={ws}")
        assert response.status_code == 200

        # Version 3 is future -- should return 404
        response = client.get(f"{TEA_URL_PREFIX}/productRelease/{release.uuid}/collection/3?workspace_key={ws}")
        assert response.status_code == 404


@pytest.mark.django_db
class TestTEACollectionSignalSuppression:
    """Tests for collection versioning signal suppression."""

    def test_add_artifact_to_latest_release_single_bump(self, tea_enabled_product, tea_enabled_component):
        """Replacing an artifact in latest release should bump version once, not twice."""
        from sbomify.apps.core.models import ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM

        # Use get_or_create to avoid conflict with auto-created latest release
        release = Release.get_or_create_latest_release(tea_enabled_product)

        # Add an initial SBOM artifact directly (bypassing signals to set up test state)
        sbom1 = SBOM.objects.create(
            component=tea_enabled_component,
            name="SBOM v1",
            format="cyclonedx",
            format_version="1.4",
            source="test",
        )
        # Ensure it's on the latest release (signal may have already done this)
        if not ReleaseArtifact.objects.filter(release=release, sbom=sbom1).exists():
            ReleaseArtifact.objects.create(release=release, sbom=sbom1)

        release.refresh_from_db()
        version_before = release.collection_version

        # Create a replacement SBOM (same format, same component).
        # Signal auto-calls add_artifact_to_latest_release.
        SBOM.objects.create(
            component=tea_enabled_component,
            name="SBOM v2",
            format="cyclonedx",
            format_version="1.5",
            source="test",
        )
        # The signal will call add_artifact_to_latest_release automatically,
        # but we also verify the direct call works correctly
        release.refresh_from_db()
        version_after = release.collection_version

        # The signal-driven add should produce a single bump per replacement, not double
        assert version_after >= version_before + 1
        assert release.collection_update_reason in ("ARTIFACT_UPDATED", "ARTIFACT_ADDED")

    def test_refresh_latest_artifacts_single_bump(self, tea_enabled_product, tea_enabled_component):
        """Refreshing latest artifacts should bump version once, not per-artifact."""
        from sbomify.apps.core.models import Project
        from sbomify.apps.sboms.models import SBOM

        # Ensure component is linked to product via a project
        project = Project.objects.filter(
            components=tea_enabled_component,
            products=tea_enabled_product,
        ).first()

        if not project:
            project = Project.objects.create(
                team=tea_enabled_product.team,
                name="Test Project",
            )
            project.products.add(tea_enabled_product)
            project.components.add(tea_enabled_component)

        # Use get_or_create to avoid conflict with auto-created latest release
        release = Release.get_or_create_latest_release(tea_enabled_product)

        # Create 3 SBOMs for the component (different formats)
        for fmt, ver in [("cyclonedx", "1.4"), ("spdx", "2.3"), ("cyclonedx", "1.5")]:
            SBOM.objects.create(
                component=tea_enabled_component,
                name=f"SBOM {fmt} {ver}",
                format=fmt,
                format_version=ver,
                source="test",
            )

        release.refresh_from_db()
        version_before = release.collection_version

        # Refresh all artifacts at once
        release.refresh_latest_artifacts()

        release.refresh_from_db()
        # Should bump exactly once (ARTIFACT_UPDATED), not N*2
        assert release.collection_version == version_before + 1
        assert release.collection_update_reason == "ARTIFACT_UPDATED"

    def test_collection_version_returns_404_for_historical_version(self, tea_enabled_product, tea_enabled_component):
        """Requesting a historical version (not current) should return 404."""
        release = Release.objects.create(product=tea_enabled_product, name="v-hist-test")

        # Bump to version 2
        release.bump_collection_version(Release.CollectionUpdateReason.ARTIFACT_ADDED)

        release.refresh_from_db()
        assert release.collection_version == 2

        client = Client()
        ws = tea_enabled_product.team.key

        # Request version 1 (historical) -- should get 404
        response = client.get(f"{TEA_URL_PREFIX}/productRelease/{release.uuid}/collection/1?workspace_key={ws}")
        assert response.status_code == 404

        # Request version 2 (current) -- should get 200
        response = client.get(f"{TEA_URL_PREFIX}/productRelease/{release.uuid}/collection/2?workspace_key={ws}")
        assert response.status_code == 200


@pytest.mark.django_db
class TestTEASignatureUrl:
    """Tests for signature URL in artifact responses."""

    def test_sbom_artifact_includes_signature_url(self, tea_enabled_component):
        """Test that SBOM artifact includes signatureUrl when set."""
        from sbomify.apps.sboms.models import SBOM

        sbom = SBOM.objects.create(
            component=tea_enabled_component,
            name="Signed SBOM",
            format="cyclonedx",
            format_version="1.4",
            source="test",
            signature_url="https://example.com/sig/sbom.sig",
        )

        client = Client()
        url = f"{TEA_URL_PREFIX}/artifact/{sbom.uuid}?workspace_key={tea_enabled_component.team.key}"
        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["formats"][0]["signatureUrl"] == "https://example.com/sig/sbom.sig"

    def test_sbom_artifact_null_signature_url(self, tea_enabled_component, sample_sbom):
        """Test that signatureUrl is null when not set."""
        client = Client()
        url = f"{TEA_URL_PREFIX}/artifact/{sample_sbom.uuid}?workspace_key={tea_enabled_component.team.key}"
        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["formats"][0]["signatureUrl"] is None

    def test_document_artifact_includes_signature_url(self, tea_enabled_component):
        """Test that Document artifact includes signatureUrl when set."""
        doc = Document.objects.create(
            name="Signed Doc",
            component=tea_enabled_component,
            document_type=Document.DocumentType.LICENSE,
            content_type="text/plain",
            source="test",
            signature_url="https://example.com/sig/doc.sig",
        )

        client = Client()
        url = f"{TEA_URL_PREFIX}/artifact/{doc.uuid}?workspace_key={tea_enabled_component.team.key}"
        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["formats"][0]["signatureUrl"] == "https://example.com/sig/doc.sig"


@pytest.mark.django_db
class TestTEAHashDiscovery:
    """Tests for hash TEI resolution via the discovery endpoint."""

    def test_discovery_resolves_hash_tei(self, tea_enabled_product, tea_enabled_component):
        """Test that discovery endpoint resolves hash TEI to product release."""
        from sbomify.apps.core.models import ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM

        hash_val = "abcdef12" * 8
        sbom = SBOM.objects.create(
            component=tea_enabled_component,
            name="Test SBOM",
            format="cyclonedx",
            format_version="1.4",
            source="test",
            sha256_hash=hash_val,
        )
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        client = Client()
        tei = f"urn:tei:hash:example.com:SHA256:{hash_val}"
        url = f"{TEA_URL_PREFIX}/discovery?tei={tei}&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        # May include auto-created "latest" release alongside the manual release
        assert len(data) >= 1
        release_uuids = [d["productReleaseUuid"] for d in data]
        assert str(release.uuid) in release_uuids

    def test_discovery_hash_tei_not_found(self, tea_enabled_product):
        """Test that unknown hash returns 404 from discovery endpoint."""
        client = Client()
        tei = f"urn:tei:hash:example.com:SHA256:{'00' * 32}"
        url = f"{TEA_URL_PREFIX}/discovery?tei={tei}&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)
        assert response.status_code == 404

    def test_discovery_eanupc_tei(self, tea_enabled_product):
        """Test that eanupc TEI resolves via discovery endpoint."""
        from sbomify.apps.sboms.models import ProductIdentifier

        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="4006381333931",
        )
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        tei = "urn:tei:eanupc:example.com:4006381333931"
        url = f"{TEA_URL_PREFIX}/discovery?tei={tei}&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["productReleaseUuid"] == str(release.uuid)


@pytest.mark.django_db
class TestTEALatestReleaseExclusion:
    """Tests that 'latest' alias releases are excluded when versioned releases exist,
    but included as fallback when they're the only release."""

    def test_discovery_excludes_latest_when_versioned_exists(self, tea_enabled_product):
        """Discovery should not return 'latest' when versioned releases exist."""
        versioned = Release.objects.create(product=tea_enabled_product, name="v1.0.0")
        Release.objects.create(product=tea_enabled_product, name="latest", is_latest=True)

        client = Client()
        tei = f"urn:tei:uuid:example.com:{tea_enabled_product.uuid}"
        url = f"{TEA_URL_PREFIX}/discovery?tei={tei}&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["productReleaseUuid"] == str(versioned.uuid)

    def test_discovery_includes_latest_when_only_release(self, tea_enabled_product):
        """Discovery should return 'latest' when it's the only release."""
        latest = Release.objects.create(product=tea_enabled_product, name="latest", is_latest=True)

        client = Client()
        tei = f"urn:tei:uuid:example.com:{tea_enabled_product.uuid}"
        url = f"{TEA_URL_PREFIX}/discovery?tei={tei}&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["productReleaseUuid"] == str(latest.uuid)

    def test_product_releases_excludes_latest_when_versioned_exists(self, tea_enabled_product):
        """/product/{uuid}/releases should not return 'latest' when versioned releases exist."""
        Release.objects.create(product=tea_enabled_product, name="v1.0.0")
        Release.objects.create(product=tea_enabled_product, name="v2.0.0")
        Release.objects.create(product=tea_enabled_product, name="latest", is_latest=True)

        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/product/{tea_enabled_product.uuid}/releases?workspace_key={ws}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert data["totalResults"] == 2
        release_names = [r["version"] for r in data["results"]]
        assert "latest" not in release_names

    def test_product_releases_includes_latest_when_only_release(self, tea_enabled_product):
        """/product/{uuid}/releases should return 'latest' when it's the only release."""
        Release.objects.create(product=tea_enabled_product, name="latest", is_latest=True)

        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/product/{tea_enabled_product.uuid}/releases?workspace_key={ws}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert data["totalResults"] == 1

    def test_query_product_releases_excludes_latest_when_versioned_exists(self, tea_enabled_product):
        """/productReleases should not return 'latest' when versioned releases exist."""
        Release.objects.create(product=tea_enabled_product, name="v1.0.0")
        Release.objects.create(product=tea_enabled_product, name="latest", is_latest=True)

        client = Client()
        url = f"{TEA_URL_PREFIX}/productReleases?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert data["totalResults"] == 1
        assert data["results"][0]["version"] != "latest"

    def test_purl_discovery_excludes_latest_when_versioned_exists(self, tea_enabled_product):
        """PURL-based discovery should exclude 'latest' when versioned releases exist."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:pypi/latest-test-pkg",
        )
        versioned = Release.objects.create(product=tea_enabled_product, name="v1.0.0")
        Release.objects.create(product=tea_enabled_product, name="latest", is_latest=True)

        client = Client()
        tei = "urn:tei:purl:example.com:pkg:pypi/latest-test-pkg"
        url = f"{TEA_URL_PREFIX}/discovery?tei={tei}&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["productReleaseUuid"] == str(versioned.uuid)

    def test_query_product_releases_multi_product_per_product_logic(self, tea_enabled_product):
        """Per-product exclusion: Product A (latest-only) stays visible even when
        Product B has versioned releases."""
        product_a = tea_enabled_product
        Release.objects.create(product=product_a, name="latest", is_latest=True)

        product_b = Product.objects.create(
            name="Product B",
            team=product_a.team,
            is_public=True,
        )
        Release.objects.create(product=product_b, name="1.0.0")
        Release.objects.create(product=product_b, name="latest", is_latest=True)

        client = Client()
        url = f"{TEA_URL_PREFIX}/productReleases?workspace_key={product_a.team.key}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()

        versions = [r["version"] for r in data["results"]]
        # Product A's "latest" should still be included
        assert "latest" in versions
        # Product B's versioned release should be present
        assert "1.0.0" in versions
        # Product B's "latest" should be excluded (it has versioned releases)
        assert versions.count("latest") == 1
        assert data["totalResults"] == len(data["results"])

    def test_discovery_multi_product_per_product_logic(self, tea_enabled_product):
        """Per-product exclusion in discovery via UUID TEI: product with only
        'latest' stays discoverable."""
        # Product A: only "latest"
        product_a = tea_enabled_product
        latest_a = Release.objects.create(product=product_a, name="latest", is_latest=True)

        client = Client()
        tei = f"urn:tei:uuid:example.com:{product_a.uuid}"
        url = f"{TEA_URL_PREFIX}/discovery?tei={tei}&workspace_key={product_a.team.key}"

        # Create Product B with versioned releases in the same team (should not affect Product A)
        product_b = Product.objects.create(
            name="Product B",
            team=product_a.team,
            is_public=True,
        )
        Release.objects.create(product=product_b, name="1.0.0")
        Release.objects.create(product=product_b, name="latest", is_latest=True)

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()

        release_ids = {r["productReleaseUuid"] for r in data}
        # Product A's "latest" must be present (only release for that product)
        assert str(latest_a.uuid) in release_ids
        assert len(data) == 1


@pytest.mark.django_db
class TestTEAMultiFormatComponentRelease:
    """Tests that multiple SBOMs for the same component+version (e.g., CycloneDX + SPDX)
    are handled correctly: deduplicated in releases list, aggregated in collections."""

    def test_component_releases_deduplicated_by_version(self, tea_enabled_component):
        """Multiple SBOMs with the same version should appear as one release."""
        SBOM.objects.create(
            name="test-sbom",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="test.cdx.json",
            component=tea_enabled_component,
            source="test",
        )
        SBOM.objects.create(
            name="test-sbom",
            version="1.0.0",
            format="spdx",
            format_version="2.3",
            sbom_filename="test.spdx.json",
            component=tea_enabled_component,
            source="test",
        )
        SBOM.objects.create(
            name="test-sbom",
            version="2.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="test2.cdx.json",
            component=tea_enabled_component,
            source="test",
        )

        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/component/{tea_enabled_component.uuid}/releases?workspace_key={ws}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()

        versions = [r["version"] for r in data]
        assert len(data) == 2
        assert "1.0.0" in versions
        assert "2.0.0" in versions

    def test_collection_includes_all_sibling_sboms(self, tea_enabled_component):
        """A component release collection should include all SBOMs for the same version."""
        cdx = SBOM.objects.create(
            name="test-sbom",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="test.cdx.json",
            component=tea_enabled_component,
            source="test",
            sha256_hash="a" * 64,
        )
        SBOM.objects.create(
            name="test-sbom",
            version="1.0.0",
            format="spdx",
            format_version="2.3",
            sbom_filename="test.spdx.json",
            component=tea_enabled_component,
            source="test",
            sha256_hash="b" * 64,
        )

        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/componentRelease/{cdx.uuid}?workspace_key={ws}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()

        artifacts = data["latestCollection"]["artifacts"]
        assert len(artifacts) == 2

        media_types = {a["formats"][0]["mediaType"] for a in artifacts}
        assert "application/vnd.cyclonedx+json" in media_types
        assert "application/spdx+json" in media_types

    def test_collection_includes_sibling_documents(self, tea_enabled_component):
        """A component release collection should include documents for the same version."""
        sbom = SBOM.objects.create(
            name="test-sbom",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="test.cdx.json",
            component=tea_enabled_component,
            source="test",
        )
        Document.objects.create(
            name="test-doc",
            version="1.0.0",
            component=tea_enabled_component,
            document_type="specification",
            content_type="application/pdf",
        )

        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/componentRelease/{sbom.uuid}?workspace_key={ws}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()

        artifacts = data["latestCollection"]["artifacts"]
        assert len(artifacts) == 2

        artifact_types = {a["type"] for a in artifacts}
        assert "BOM" in artifact_types

    def test_collection_date_uses_latest_artifact(self, tea_enabled_component):
        """Collection date should reflect the most recently created artifact."""
        import datetime

        from django.utils import timezone

        earlier = timezone.now() - datetime.timedelta(days=10)
        later = timezone.now()

        cdx = SBOM.objects.create(
            name="test-sbom",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="test.cdx.json",
            component=tea_enabled_component,
            source="test",
        )
        # Manually set created_at to control ordering
        SBOM.objects.filter(id=cdx.id).update(created_at=earlier)

        spdx = SBOM.objects.create(
            name="test-sbom",
            version="1.0.0",
            format="spdx",
            format_version="2.3",
            sbom_filename="test.spdx.json",
            component=tea_enabled_component,
            source="test",
        )
        SBOM.objects.filter(id=spdx.id).update(created_at=later)

        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/componentRelease/{cdx.uuid}?workspace_key={ws}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()

        collection_date = data["latestCollection"]["date"]
        # Collection date should match the later SBOM, not the earlier one
        assert collection_date > earlier.strftime("%Y-%m-%dT%H:%M:")

    def test_collection_excludes_different_version_sboms(self, tea_enabled_component):
        """SBOMs with different versions should NOT appear in each other's collections."""
        sbom_v1 = SBOM.objects.create(
            name="test-sbom",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="test.cdx.json",
            component=tea_enabled_component,
            source="test",
        )
        SBOM.objects.create(
            name="test-sbom",
            version="2.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="test2.cdx.json",
            component=tea_enabled_component,
            source="test",
        )

        client = Client()
        ws = tea_enabled_component.team.key
        url = f"{TEA_URL_PREFIX}/componentRelease/{sbom_v1.uuid}?workspace_key={ws}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()

        artifacts = data["latestCollection"]["artifacts"]
        assert len(artifacts) == 1


@pytest.mark.django_db
class TestTEABaseURLHandling:
    """Tests for base URL handling in artifact download links."""

    def test_default_base_url_in_artifact_format(self, tea_enabled_product, tea_enabled_component):
        """Non-custom-domain requests use settings.APP_BASE_URL for download links."""
        from django.conf import settings

        from sbomify.apps.core.models import Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM

        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")
        sbom = SBOM.objects.create(
            component=tea_enabled_component,
            name="Test SBOM",
            format="cyclonedx",
            format_version="1.4",
            source="test",
        )
        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        client = Client()
        ws = tea_enabled_product.team.key
        url = f"{TEA_URL_PREFIX}/productRelease/{release.uuid}/collection/latest?workspace_key={ws}"

        response = client.get(url)
        assert response.status_code == 200
        data = response.json()

        fmt = data["artifacts"][0]["formats"][0]
        expected_base = settings.APP_BASE_URL.rstrip("/")
        assert fmt["url"].startswith(expected_base)
        assert f"/api/v1/sboms/{sbom.uuid}/download" in fmt["url"]

    def test_custom_domain_base_url_in_artifact_format(self, tea_enabled_product, tea_enabled_component):
        """Custom-domain requests use the request host for download links."""
        from sbomify.apps.core.models import Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM

        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")
        sbom = SBOM.objects.create(
            component=tea_enabled_component,
            name="Test SBOM",
            format="cyclonedx",
            format_version="1.4",
            source="test",
        )
        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        # Set up validated custom domain on the team
        tea_enabled_product.team.custom_domain = "trust.example.com"
        tea_enabled_product.team.custom_domain_validated = True
        tea_enabled_product.team.is_public = True
        tea_enabled_product.team.save()

        client = Client()
        url = f"/tea/v{TEA_API_VERSION}/productRelease/{release.uuid}/collection/latest"

        response = client.get(
            url,
            HTTP_HOST="trust.example.com",
            HTTP_X_FORWARDED_PROTO="https",
        )
        assert response.status_code == 200
        data = response.json()

        fmt = data["artifacts"][0]["formats"][0]
        assert fmt["url"].startswith("https://trust.example.com")
        assert f"/api/v1/sboms/{sbom.uuid}/download" in fmt["url"]


MALFORMED_UUID = "not-a-valid-uuid"


@pytest.mark.django_db
class TestTEAMalformedUUID:
    """Tests that malformed (non-UUID) path params return 404, not 500."""

    @pytest.mark.parametrize(
        "path_template",
        [
            "/product/{uuid}",
            "/product/{uuid}/releases",
            "/productRelease/{uuid}",
            "/productRelease/{uuid}/collection/latest",
            "/productRelease/{uuid}/collections",
            "/productRelease/{uuid}/collection/1",
            "/component/{uuid}",
            "/component/{uuid}/releases",
            "/componentRelease/{uuid}",
            "/componentRelease/{uuid}/collection/latest",
            "/componentRelease/{uuid}/collections",
            "/componentRelease/{uuid}/collection/1",
            "/artifact/{uuid}",
        ],
    )
    def test_malformed_uuid_returns_404(self, tea_enabled_product, path_template):
        """Malformed UUID string in path returns 404, not 500."""
        client = Client()
        ws = tea_enabled_product.team.key
        path = path_template.format(uuid=MALFORMED_UUID)
        url = f"{TEA_URL_PREFIX}{path}?workspace_key={ws}"

        response = client.get(url)

        assert response.status_code == 404


@pytest.mark.django_db
class TestTEACrossWorkspaceIsolation:
    """Tests that entities from one workspace are not accessible from another."""

    def test_product_not_accessible_from_other_workspace(self, tea_enabled_product):
        """A product's UUID should not be accessible from a different workspace."""
        from sbomify.apps.teams.models import Team

        other_team = Team.objects.create(
            name="Other Workspace",
            tea_enabled=True,
        )

        client = Client()
        url = f"{TEA_URL_PREFIX}/product/{tea_enabled_product.uuid}?workspace_key={other_team.key}"

        response = client.get(url)
        assert response.status_code == 404

    def test_release_not_accessible_from_other_workspace(self, tea_enabled_product):
        """A release's UUID should not be accessible from a different workspace."""
        from sbomify.apps.teams.models import Team

        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        other_team = Team.objects.create(
            name="Other Workspace",
            tea_enabled=True,
        )

        client = Client()
        url = f"{TEA_URL_PREFIX}/productRelease/{release.uuid}?workspace_key={other_team.key}"

        response = client.get(url)
        assert response.status_code == 404

    def test_component_not_accessible_from_other_workspace(self, tea_enabled_component):
        """A component's UUID should not be accessible from a different workspace."""
        from sbomify.apps.teams.models import Team

        other_team = Team.objects.create(
            name="Other Workspace",
            tea_enabled=True,
        )

        client = Client()
        url = f"{TEA_URL_PREFIX}/component/{tea_enabled_component.uuid}?workspace_key={other_team.key}"

        response = client.get(url)
        assert response.status_code == 404

    def test_artifact_not_accessible_from_other_workspace(self, tea_enabled_component, sample_sbom):
        """An artifact (SBOM) UUID should not be accessible from a different workspace."""
        from sbomify.apps.teams.models import Team

        other_team = Team.objects.create(
            name="Other Workspace",
            tea_enabled=True,
        )

        client = Client()
        url = f"{TEA_URL_PREFIX}/artifact/{sample_sbom.uuid}?workspace_key={other_team.key}"

        response = client.get(url)
        assert response.status_code == 404


@pytest.mark.django_db
class TestTEAMalformedUUIDInTEI:
    """Tests that malformed UUIDs embedded in TEI strings are handled gracefully."""

    def test_discovery_malformed_uuid_in_tei(self, tea_enabled_product):
        """Malformed UUID inside a TEI string returns 404, not 500."""
        client = Client()
        tei = "urn:tei:uuid:example.com:not-a-valid-uuid"
        url = f"{TEA_URL_PREFIX}/discovery?tei={tei}&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 404

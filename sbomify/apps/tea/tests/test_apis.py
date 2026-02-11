"""
Integration tests for TEA API endpoints.
"""

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.sboms.models import ProductIdentifier, SBOM


@pytest.fixture
def tea_enabled_product(sample_product):
    """Product with TEA enabled on its team."""
    sample_product.is_public = True
    sample_product.save()
    sample_product.team.tea_enabled = True
    sample_product.team.save()
    return sample_product


@pytest.fixture
def tea_enabled_component(sample_component):
    """Component with TEA enabled on its team."""
    sample_component.visibility = Component.Visibility.PUBLIC
    sample_component.save()
    sample_component.team.tea_enabled = True
    sample_component.team.save()
    return sample_component


@pytest.mark.django_db
class TestTEADiscoveryEndpoint:
    """Tests for /tea/v1/discovery endpoint."""

    def test_discovery_with_uuid_tei(self, tea_enabled_product):
        """Test discovery with UUID TEI type."""
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        tei = f"urn:tei:uuid:example.com:{tea_enabled_product.id}"
        url = f"/tea/v1/discovery?tei={tei}&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

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
        url = f"/tea/v1/discovery?tei={tei}&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    def test_discovery_invalid_tei(self, tea_enabled_product):
        """Test discovery with invalid TEI format."""
        client = Client()
        url = f"/tea/v1/discovery?tei=invalid-tei&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 400

    def test_discovery_no_match(self, tea_enabled_product):
        """Test discovery with no matching releases."""
        client = Client()
        tei = "urn:tei:uuid:example.com:nonexistent-id"
        url = f"/tea/v1/discovery?tei={tei}&workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 404

    def test_discovery_invalid_workspace(self):
        """Test discovery with invalid workspace."""
        client = Client()
        tei = "urn:tei:uuid:example.com:some-id"
        url = f"/tea/v1/discovery?tei={tei}&workspace_key=nonexistent"

        response = client.get(url)

        assert response.status_code == 400


@pytest.mark.django_db
class TestTEAProductsEndpoint:
    """Tests for /tea/v1/products endpoint."""

    def test_list_products(self, tea_enabled_product):
        """Test listing all products."""
        client = Client()
        url = f"/tea/v1/products?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert "timestamp" in data
        assert "pageStartIndex" in data
        assert "pageSize" in data
        assert "totalResults" in data
        assert "results" in data
        assert data["totalResults"] >= 1

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
        url = f"/tea/v1/products?workspace_key={tea_enabled_product.team.key}&pageOffset=0&pageSize=3"

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
        url = f"/tea/v1/products?workspace_key={tea_enabled_product.team.key}&idType=PURL&idValue=test-filter"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["totalResults"] >= 1

    def test_list_products_private_excluded(self, tea_enabled_product):
        """Test that private products are excluded."""
        tea_enabled_product.is_public = False
        tea_enabled_product.save()

        client = Client()
        url = f"/tea/v1/products?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        # The sample product should not be in results since it's private
        product_ids = [p["uuid"] for p in data["results"]]
        assert tea_enabled_product.id not in product_ids


@pytest.mark.django_db
class TestTEAProductEndpoint:
    """Tests for /tea/v1/product/{uuid} endpoint."""

    def test_get_product(self, tea_enabled_product):
        """Test getting a single product."""
        client = Client()
        url = f"/tea/v1/product/{tea_enabled_product.id}?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert data["uuid"] == tea_enabled_product.id
        assert data["name"] == tea_enabled_product.name
        assert "identifiers" in data

    def test_get_product_not_found(self, tea_enabled_product):
        """Test getting a non-existent product."""
        client = Client()
        url = f"/tea/v1/product/nonexistent-id?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 404

    def test_get_private_product_not_accessible(self, tea_enabled_product):
        """Test that private products are not accessible."""
        tea_enabled_product.is_public = False
        tea_enabled_product.save()

        client = Client()
        url = f"/tea/v1/product/{tea_enabled_product.id}?workspace_key={tea_enabled_product.team.key}"

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
        url = f"/tea/v1/product/{tea_enabled_product.id}/releases?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert "results" in data
        assert data["totalResults"] >= 2

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
        url = f"/tea/v1/productRelease/{release.id}?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert data["uuid"] == release.id
        assert data["version"] == "v1.0.0"
        assert data["product"] == tea_enabled_product.id
        assert data["productName"] == tea_enabled_product.name

    def test_get_product_release_not_found(self, tea_enabled_product):
        """Test getting a non-existent release."""
        client = Client()
        url = f"/tea/v1/productRelease/nonexistent-id?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 404


@pytest.mark.django_db
class TestTEAProductReleaseCollectionEndpoints:
    """Tests for product release collection endpoints."""

    def test_get_latest_collection(self, tea_enabled_product):
        """Test getting latest collection for a product release."""
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        url = f"/tea/v1/productRelease/{release.id}/collection/latest?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert data["uuid"] == release.id
        assert data["version"] == 1
        assert data["belongsTo"] == "PRODUCT_RELEASE"
        assert "artifacts" in data

    def test_get_collections(self, tea_enabled_product):
        """Test getting all collections for a product release."""
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        url = f"/tea/v1/productRelease/{release.id}/collections?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)
        assert len(data) == 1

    def test_get_collection_by_version(self, tea_enabled_product):
        """Test getting a specific collection version."""
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        url = f"/tea/v1/productRelease/{release.id}/collection/1?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 1

    def test_get_collection_invalid_version(self, tea_enabled_product):
        """Test getting a non-existent collection version."""
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        client = Client()
        url = f"/tea/v1/productRelease/{release.id}/collection/999?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 404


@pytest.mark.django_db
class TestTEAComponentEndpoint:
    """Tests for /tea/v1/component/{uuid} endpoint."""

    def test_get_component(self, tea_enabled_component):
        """Test getting a single component."""
        client = Client()
        url = f"/tea/v1/component/{tea_enabled_component.id}?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert data["uuid"] == tea_enabled_component.id
        assert data["name"] == tea_enabled_component.name
        assert "identifiers" in data

    def test_get_component_not_found(self, tea_enabled_component):
        """Test getting a non-existent component."""
        client = Client()
        url = f"/tea/v1/component/nonexistent-id?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 404


@pytest.mark.django_db
class TestTEAComponentReleasesEndpoint:
    """Tests for /tea/v1/component/{uuid}/releases endpoint."""

    def test_get_component_releases(self, tea_enabled_component, sample_sbom):
        """Test getting releases (SBOMs) for a component."""
        client = Client()
        url = f"/tea/v1/component/{tea_enabled_component.id}/releases?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)
        assert len(data) >= 1

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
        url = f"/tea/v1/componentRelease/{sample_sbom.id}?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert "release" in data
        assert "latestCollection" in data
        assert data["release"]["uuid"] == sample_sbom.id
        assert data["latestCollection"]["belongsTo"] == "COMPONENT_RELEASE"

    def test_get_component_release_not_found(self, tea_enabled_component):
        """Test getting a non-existent component release."""
        client = Client()
        url = f"/tea/v1/componentRelease/nonexistent-id?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 404


@pytest.mark.django_db
class TestTEAArtifactEndpoint:
    """Tests for /tea/v1/artifact/{uuid} endpoint."""

    def test_get_sbom_artifact(self, tea_enabled_component, sample_sbom):
        """Test getting an SBOM artifact."""
        client = Client()
        url = f"/tea/v1/artifact/{sample_sbom.id}?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert data["uuid"] == sample_sbom.id
        assert data["type"] == "BOM"
        assert "formats" in data
        assert len(data["formats"]) >= 1

    def test_get_artifact_not_found(self, tea_enabled_component):
        """Test getting a non-existent artifact."""
        client = Client()
        url = f"/tea/v1/artifact/nonexistent-id?workspace_key={tea_enabled_component.team.key}"

        response = client.get(url)

        assert response.status_code == 404


@pytest.mark.django_db
class TestTEAProductReleasesQueryEndpoint:
    """Tests for /tea/v1/productReleases endpoint."""

    def test_query_product_releases(self, tea_enabled_product):
        """Test querying product releases."""
        Release.objects.create(product=tea_enabled_product, name="v1.0.0")
        Release.objects.create(product=tea_enabled_product, name="v2.0.0")

        client = Client()
        url = f"/tea/v1/productReleases?workspace_key={tea_enabled_product.team.key}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert "timestamp" in data
        assert "results" in data
        assert data["totalResults"] >= 2

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
        url = f"/tea/v1/productReleases?workspace_key={tea_enabled_product.team.key}&idType=CPE&idValue=test:product"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["totalResults"] >= 1


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
        url = f"/tea/v1/products?workspace_key={sample_product.team.key}"

        response = client.get(url)

        assert response.status_code == 400

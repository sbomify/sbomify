"""Tests for search functionality."""

import json

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401


@pytest.mark.django_db
class TestSearchView:
    """Test cases for SearchView."""

    def test_search_requires_authentication(self, client: Client):
        """Test that search endpoint requires authentication."""
        response = client.get(reverse("core:search"), {"q": "test"})
        assert response.status_code == 302

    def test_search_empty_query_returns_empty_results(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that empty query returns empty results."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        response = client.get(reverse("core:search"), {"q": ""})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["products"] == []
        assert data["components"] == []

    def test_search_short_query_returns_empty_results(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that query shorter than 2 characters returns empty results."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        response = client.get(reverse("core:search"), {"q": "a"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["products"] == []
        assert data["components"] == []

    def test_search_products(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test searching for products."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        Product.objects.create(
            name="Test Product",
            description="A test product description",
            team=team,
        )
        Product.objects.create(
            name="Another Product",
            description="Different product",
            team=team,
        )

        response = client.get(reverse("core:search"), {"q": "Test"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) == 1
        assert data["products"][0]["name"] == "Test Product"
        assert "test product description" in data["products"][0]["description"].lower()

    def test_search_components(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test searching for components."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        Component.objects.create(
            name="Test Component",
            team=team,
            component_type=Component.ComponentType.BOM,
        )
        Component.objects.create(
            name="Another Component",
            team=team,
            component_type=Component.ComponentType.DOCUMENT,
        )

        response = client.get(reverse("core:search"), {"q": "Test"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["components"]) == 1
        assert data["components"][0]["name"] == "Test Component"
        assert data["components"][0]["component_type"] == "bom"

    def test_search_respects_team_scope(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that search only returns results from current team."""
        from sbomify.apps.teams.models import Member, Workspace

        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        other_team = Workspace.objects.create(name="Other Team")
        Member.objects.create(team=other_team, user=user, role="owner")

        Product.objects.create(name="Team Product", team=team)
        Product.objects.create(name="Other Team Product", team=other_team)

        response = client.get(reverse("core:search"), {"q": "Product"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) == 1
        assert data["products"][0]["name"] == "Team Product"

    def test_search_limit_parameter(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that limit parameter works correctly."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        for i in range(15):
            Product.objects.create(name=f"Product {i}", team=team)

        response = client.get(reverse("core:search"), {"q": "Product", "limit": 5})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) == 5

    def test_search_limit_validation_max(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that limit is capped at maximum value."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        for i in range(100):
            Product.objects.create(name=f"Product {i}", team=team)

        response = client.get(reverse("core:search"), {"q": "Product", "limit": 1000})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) <= 50

    def test_search_limit_validation_min(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that limit is enforced at minimum value."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        Product.objects.create(name="Product 1", team=team)
        Product.objects.create(name="Product 2", team=team)

        response = client.get(reverse("core:search"), {"q": "Product", "limit": 0})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) >= 1

    def test_search_limit_invalid_type(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that invalid limit type defaults to 10."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        for i in range(15):
            Product.objects.create(name=f"Product {i}", team=team)

        response = client.get(reverse("core:search"), {"q": "Product", "limit": "invalid"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) == 10

    def test_search_case_insensitive(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that search is case insensitive."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        Product.objects.create(name="Test Product", team=team)

        response = client.get(reverse("core:search"), {"q": "test"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) == 1

        response = client.get(reverse("core:search"), {"q": "TEST"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) == 1

    def test_search_no_team_returns_empty(
        self, client: Client, sample_user: AbstractBaseUser
    ):
        """Test that search without team returns empty results."""
        client.force_login(sample_user)

        response = client.get(reverse("core:search"), {"q": "test"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["products"] == []
        assert data["components"] == []


    def test_search_product_by_id(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
        product = Product.objects.create(name="Billing", team=team)
        Product.objects.create(name="Other", team=team)

        data = client.get(reverse("core:search"), {"q": product.id}).json()

        assert [p["id"] for p in data["products"]] == [product.id]
        asset_urls = [r["url"] for r in data["results"] if r["section"] == "assets"]
        assert reverse("core:product_details", kwargs={"product_id": product.id}) in asset_urls

    def test_search_component_by_id(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
        component = Component.objects.create(name="api", team=team)

        data = client.get(reverse("core:search"), {"q": component.id}).json()

        assert [c["id"] for c in data["components"]] == [component.id]
        asset_urls = [r["url"] for r in data["results"] if r["section"] == "assets"]
        assert reverse("core:component_details", kwargs={"component_id": component.id}) in asset_urls

    def test_search_by_uuid(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
        product = Product.objects.create(name="Billing", team=team)
        component = Component.objects.create(name="api", team=team)

        products = client.get(reverse("core:search"), {"q": str(product.uuid)}).json()["products"]
        components = client.get(reverse("core:search"), {"q": str(component.uuid)}).json()["components"]

        assert [p["id"] for p in products] == [product.id]
        assert [c["id"] for c in components] == [component.id]

    def test_search_by_partial_id_does_not_match(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
        product = Product.objects.create(name="Billing", team=team)

        data = client.get(reverse("core:search"), {"q": product.id[:6]}).json()

        assert data["products"] == []

    def test_search_by_id_respects_team_scope(self, client: Client, sample_team_with_owner_member):
        from sbomify.apps.teams.models import Workspace

        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
        other_team = Workspace.objects.create(name="Other Team")
        product = Product.objects.create(name="Secret", team=other_team)
        component = Component.objects.create(name="secret", team=other_team)

        for query in (product.id, str(product.uuid), component.id):
            data = client.get(reverse("core:search"), {"q": query}).json()
            assert data["products"] == []
            assert data["components"] == []

    def test_search_id_match_is_not_cut_by_limit(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
        target = Product.objects.create(name="zzz", team=team)
        for i in range(3):
            Product.objects.create(name=f"aaa {target.id} {i}", team=team)

        data = client.get(reverse("core:search"), {"q": target.id, "limit": 2}).json()

        assert len(data["products"]) == 2
        assert data["products"][0]["id"] == target.id

    @staticmethod
    def _section_urls(data: dict, section: str) -> list[str]:
        return [r["url"] for r in data["results"] if r["section"] == section]

    def test_search_release_by_id_and_uuid(self, client: Client, sample_team_with_owner_member):
        from sbomify.apps.core.models import Release

        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
        product = Product.objects.create(name="Billing", team=team)
        release = Release.objects.create(product=product, name="v1")
        url = reverse("core:release_details", kwargs={"product_id": product.id, "release_id": release.id})

        for query in (release.id, str(release.uuid)):
            data = client.get(reverse("core:search"), {"q": query}).json()
            assert self._section_urls(data, "releases") == [url]

    def test_search_component_release_by_id(self, client: Client, sample_team_with_owner_member):
        from sbomify.apps.core.models import ComponentRelease

        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
        component = Component.objects.create(name="api", team=team)
        component_release = ComponentRelease.objects.create(component=component, version="2.0.0")

        data = client.get(reverse("core:search"), {"q": component_release.id}).json()

        releases = [r for r in data["results"] if r["section"] == "releases"]
        assert [r["title"] for r in releases] == ["2.0.0 · api"]
        assert releases[0]["url"] == reverse("core:component_details", kwargs={"component_id": component.id})

    def test_search_component_release_by_version_is_not_listed(self, client: Client, sample_team_with_owner_member):
        from sbomify.apps.core.models import ComponentRelease

        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
        component = Component.objects.create(name="api", team=team)
        ComponentRelease.objects.create(component=component, version="2.0.0")

        data = client.get(reverse("core:search"), {"q": "2.0.0"}).json()

        assert self._section_urls(data, "releases") == []

    def test_search_sbom_by_id(self, client: Client, sample_team_with_owner_member):
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
        component = Component.objects.create(name="api", team=team)
        sbom = SBOM.objects.create(name="pkg", version="1.0", component=component, format="cyclonedx")
        url = reverse(
            "core:component_item", kwargs={"component_id": component.id, "item_type": "sboms", "item_id": sbom.id}
        )

        for query in (sbom.id, str(sbom.uuid)):
            data = client.get(reverse("core:search"), {"q": query}).json()
            assert self._section_urls(data, "artifacts") == [url]
        assert self._section_urls(client.get(reverse("core:search"), {"q": "pkg"}).json(), "artifacts") == []

    def test_search_document_by_id(self, client: Client, sample_team_with_owner_member):
        from sbomify.apps.documents.models import Document

        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
        component = Component.objects.create(name="api", team=team)
        document = Document.objects.create(name="Policy", component=component)

        data = client.get(reverse("core:search"), {"q": document.id}).json()

        assert [r["title"] for r in data["results"] if r["section"] == "documents"] == ["Policy · api"]

    def test_search_by_pasted_link(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
        product = Product.objects.create(name="Billing", team=team)
        component = Component.objects.create(name="api", team=team)

        product_link = f"https://app.sbomify.com/product/{product.id}/?tab=releases#top"
        component_link = f"app.sbomify.com/component/{component.id}/"

        assert [p["id"] for p in client.get(reverse("core:search"), {"q": product_link}).json()["products"]] == [
            product.id
        ]
        assert [c["id"] for c in client.get(reverse("core:search"), {"q": component_link}).json()["components"]] == [
            component.id
        ]

    def test_search_by_pasted_release_link_finds_product_and_release(
        self, client: Client, sample_team_with_owner_member
    ):
        from sbomify.apps.core.models import Release

        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
        product = Product.objects.create(name="Billing", team=team)
        release = Release.objects.create(product=product, name="v1")
        path = reverse("core:release_details", kwargs={"product_id": product.id, "release_id": release.id})

        data = client.get(reverse("core:search"), {"q": f"https://app.sbomify.com{path}"}).json()

        assert [p["id"] for p in data["products"]] == [product.id]
        assert self._section_urls(data, "releases") == [path]

    def test_search_by_id_for_other_workspace_records_returns_nothing(
        self, client: Client, sample_team_with_owner_member
    ):
        from sbomify.apps.core.models import ComponentRelease, Release
        from sbomify.apps.documents.models import Document
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.teams.models import Workspace

        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
        other_team = Workspace.objects.create(name="Other Team")
        product = Product.objects.create(name="Secret", team=other_team)
        component = Component.objects.create(name="secret", team=other_team)
        records = [
            Release.objects.create(product=product, name="v1"),
            ComponentRelease.objects.create(component=component, version="1.0"),
            SBOM.objects.create(name="pkg", component=component, format="cyclonedx"),
            Document.objects.create(name="Policy", component=component),
        ]

        for record in records:
            for query in (record.id, f"https://app.sbomify.com/x/{record.id}/"):
                data = client.get(reverse("core:search"), {"q": query}).json()
                assert [r for r in data["results"] if r["section"] in ("releases", "documents", "artifacts")] == []

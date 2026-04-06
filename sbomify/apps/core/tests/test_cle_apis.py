from __future__ import annotations

import json

import pytest
from django.test import Client

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import Component, ComponentRelease, Release
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.models import Product
from sbomify.apps.teams.models import Member


@pytest.mark.django_db
class TestCLEEventsAPI:
    """Tests for CLE event endpoints."""

    def test_create_and_list_events(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_product: Product,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = f"/api/v1/products/{sample_product.pk}/cle/events"

        # Create a "released" event
        payload = {
            "event_type": "released",
            "effective": "2025-01-15T00:00:00Z",
            "version": "1.0.0",
        }
        response = client.post(url, data=payload, content_type="application/json", **headers)
        assert response.status_code == 201, response.content
        created = json.loads(response.content)
        assert created["event_type"] == "released"
        assert created["version"] == "1.0.0"
        assert created["event_id"] == 1

        # Create a second event
        payload2 = {
            "event_type": "released",
            "effective": "2025-06-01T00:00:00Z",
            "version": "2.0.0",
        }
        response2 = client.post(url, data=payload2, content_type="application/json", **headers)
        assert response2.status_code == 201, response2.content

        # List — should return newest first
        response_list = client.get(url, **headers)
        assert response_list.status_code == 200
        items = json.loads(response_list.content)
        assert len(items) == 2
        assert items[0]["event_id"] == 2
        assert items[1]["event_id"] == 1

    def test_get_single_event(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_product: Product,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        base_url = f"/api/v1/products/{sample_product.pk}/cle/events"

        # Create an event first
        payload = {
            "event_type": "released",
            "effective": "2025-01-15T00:00:00Z",
            "version": "1.0.0",
        }
        create_resp = client.post(base_url, data=payload, content_type="application/json", **headers)
        assert create_resp.status_code == 201, create_resp.content
        created = json.loads(create_resp.content)
        event_id = created["event_id"]

        # Get single event
        detail_url = f"{base_url}/{event_id}"
        response = client.get(detail_url, **headers)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["event_id"] == event_id
        assert data["event_type"] == "released"

        # Non-existent event
        response_404 = client.get(f"{base_url}/9999", **headers)
        assert response_404.status_code == 404

    def test_create_event_validation_error(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_product: Product,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = f"/api/v1/products/{sample_product.pk}/cle/events"

        # Missing required "versions" for endOfLife event type
        payload = {
            "event_type": "endOfLife",
            "effective": "2025-01-15T00:00:00Z",
        }
        response = client.post(url, data=payload, content_type="application/json", **headers)
        assert response.status_code == 400

    def test_create_event_invalid_event_type(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_product: Product,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = f"/api/v1/products/{sample_product.pk}/cle/events"

        payload = {
            "event_type": "invalid_type",
            "effective": "2025-01-15T00:00:00Z",
        }
        response = client.post(url, data=payload, content_type="application/json", **headers)
        assert response.status_code == 422  # Pydantic rejects invalid Literal value

    def test_product_not_found_returns_404(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = "/api/v1/products/nonexistent_id/cle/events"

        response = client.get(url, **headers)
        assert response.status_code == 404

    def test_list_events_pagination(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_product: Product,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = f"/api/v1/products/{sample_product.pk}/cle/events"

        # Create 3 events
        for i in range(3):
            payload = {
                "event_type": "released",
                "effective": f"2025-0{i + 1}-15T00:00:00Z",
                "version": f"{i + 1}.0.0",
            }
            resp = client.post(url, data=payload, content_type="application/json", **headers)
            assert resp.status_code == 201, resp.content

        # Request page of size 2
        response = client.get(f"{url}?pageSize=2", **headers)
        assert response.status_code == 200
        items = json.loads(response.content)
        assert len(items) == 2

        # Request second page
        response2 = client.get(f"{url}?pageOffset=2&pageSize=2", **headers)
        assert response2.status_code == 200
        items2 = json.loads(response2.content)
        assert len(items2) == 1


@pytest.mark.django_db
class TestCLESupportDefinitionsAPI:
    """Tests for CLE support definition endpoints."""

    def test_create_and_list_support_definitions(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_product: Product,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = f"/api/v1/products/{sample_product.pk}/cle/support-definitions"

        payload = {
            "support_id": "standard",
            "description": "Standard support tier",
            "url": "https://example.com/support",
        }
        response = client.post(url, data=payload, content_type="application/json", **headers)
        assert response.status_code == 201, response.content
        created = json.loads(response.content)
        assert created["support_id"] == "standard"
        assert created["description"] == "Standard support tier"
        assert created["url"] == "https://example.com/support"

        # List
        response_list = client.get(url, **headers)
        assert response_list.status_code == 200
        items = json.loads(response_list.content)
        assert len(items) == 1
        assert items[0]["support_id"] == "standard"

    def test_duplicate_support_definition_returns_409(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_product: Product,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = f"/api/v1/products/{sample_product.pk}/cle/support-definitions"

        payload = {
            "support_id": "premium",
            "description": "Premium support",
        }
        response1 = client.post(url, data=payload, content_type="application/json", **headers)
        assert response1.status_code == 201

        # Duplicate — should get 409 with CONFLICT error code
        response2 = client.post(url, data=payload, content_type="application/json", **headers)
        assert response2.status_code == 409
        data = json.loads(response2.content)
        assert data["error_code"] == "CONFLICT"


# ===========================================================================
# Component CLE API tests
# ===========================================================================


@pytest.mark.django_db
class TestComponentCLEAPIs:
    """Tests for Component CLE event and support definition endpoints."""

    @pytest.fixture
    def sample_component(self, sample_team_with_owner_member: Member) -> Component:
        return Component.objects.create(name="API Test Component", team=sample_team_with_owner_member.team)

    def test_create_and_list_events(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_component: Component,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = f"/api/v1/components/{sample_component.pk}/cle/events"

        payload = {
            "event_type": "released",
            "effective": "2025-01-15T00:00:00Z",
            "version": "1.0.0",
        }
        response = client.post(url, data=payload, content_type="application/json", **headers)
        assert response.status_code == 201, response.content
        created = json.loads(response.content)
        assert created["event_type"] == "released"
        assert created["event_id"] == 1

        response_list = client.get(url, **headers)
        assert response_list.status_code == 200
        items = json.loads(response_list.content)
        assert len(items) == 1

    def test_get_single_event(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_component: Component,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        base_url = f"/api/v1/components/{sample_component.pk}/cle/events"

        payload = {
            "event_type": "released",
            "effective": "2025-01-15T00:00:00Z",
            "version": "1.0.0",
        }
        create_resp = client.post(base_url, data=payload, content_type="application/json", **headers)
        assert create_resp.status_code == 201
        created = json.loads(create_resp.content)

        detail_url = f"{base_url}/{created['event_id']}"
        response = client.get(detail_url, **headers)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["event_id"] == created["event_id"]

        response_404 = client.get(f"{base_url}/9999", **headers)
        assert response_404.status_code == 404

    def test_component_not_found_returns_404(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = "/api/v1/components/nonexistent_id/cle/events"

        response = client.get(url, **headers)
        assert response.status_code == 404

    def test_create_and_list_support_definitions(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_component: Component,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = f"/api/v1/components/{sample_component.pk}/cle/support-definitions"

        payload = {
            "support_id": "standard",
            "description": "Standard support tier",
        }
        response = client.post(url, data=payload, content_type="application/json", **headers)
        assert response.status_code == 201, response.content

        response_list = client.get(url, **headers)
        assert response_list.status_code == 200
        items = json.loads(response_list.content)
        assert len(items) == 1
        assert items[0]["support_id"] == "standard"


# ===========================================================================
# Release CLE API tests
# ===========================================================================


@pytest.mark.django_db
class TestReleaseCLEAPIs:
    """Tests for Release CLE event and support definition endpoints."""

    @pytest.fixture
    def sample_release(self, sample_product: Product) -> Release:
        return Release.objects.create(name="v1.0", product=sample_product)

    def test_create_and_list_events(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_release: Release,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = f"/api/v1/releases/{sample_release.pk}/cle/events"

        payload = {
            "event_type": "released",
            "effective": "2025-01-15T00:00:00Z",
            "version": "1.0.0",
        }
        response = client.post(url, data=payload, content_type="application/json", **headers)
        assert response.status_code == 201, response.content
        created = json.loads(response.content)
        assert created["event_type"] == "released"
        assert created["event_id"] == 1

        response_list = client.get(url, **headers)
        assert response_list.status_code == 200
        items = json.loads(response_list.content)
        assert len(items) == 1

    def test_get_single_event(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_release: Release,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        base_url = f"/api/v1/releases/{sample_release.pk}/cle/events"

        payload = {
            "event_type": "released",
            "effective": "2025-01-15T00:00:00Z",
            "version": "1.0.0",
        }
        create_resp = client.post(base_url, data=payload, content_type="application/json", **headers)
        assert create_resp.status_code == 201
        created = json.loads(create_resp.content)

        detail_url = f"{base_url}/{created['event_id']}"
        response = client.get(detail_url, **headers)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["event_id"] == created["event_id"]

        response_404 = client.get(f"{base_url}/9999", **headers)
        assert response_404.status_code == 404

    def test_release_not_found_returns_404(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = "/api/v1/releases/nonexistent_id/cle/events"

        response = client.get(url, **headers)
        assert response.status_code == 404

    def test_create_and_list_support_definitions(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_release: Release,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = f"/api/v1/releases/{sample_release.pk}/cle/support-definitions"

        payload = {
            "support_id": "premium",
            "description": "Premium support tier",
            "url": "https://example.com/premium",
        }
        response = client.post(url, data=payload, content_type="application/json", **headers)
        assert response.status_code == 201, response.content

        response_list = client.get(url, **headers)
        assert response_list.status_code == 200
        items = json.loads(response_list.content)
        assert len(items) == 1
        assert items[0]["support_id"] == "premium"


# ===========================================================================
# ComponentRelease CLE API tests
# ===========================================================================


@pytest.mark.django_db
class TestComponentReleaseCLEAPIs:
    """Tests for ComponentRelease CLE event and support definition endpoints."""

    @pytest.fixture
    def sample_component_release(self, sample_team_with_owner_member: Member) -> ComponentRelease:
        component = Component.objects.create(name="CR API Component", team=sample_team_with_owner_member.team)
        return ComponentRelease.objects.create(component=component, version="1.0.0")

    def test_create_and_list_events(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_component_release: ComponentRelease,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = f"/api/v1/component-releases/{sample_component_release.pk}/cle/events"

        payload = {
            "event_type": "released",
            "effective": "2025-01-15T00:00:00Z",
            "version": "1.0.0",
        }
        response = client.post(url, data=payload, content_type="application/json", **headers)
        assert response.status_code == 201, response.content
        created = json.loads(response.content)
        assert created["event_type"] == "released"
        assert created["event_id"] == 1

        response_list = client.get(url, **headers)
        assert response_list.status_code == 200
        items = json.loads(response_list.content)
        assert len(items) == 1

    def test_get_single_event(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_component_release: ComponentRelease,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        base_url = f"/api/v1/component-releases/{sample_component_release.pk}/cle/events"

        payload = {
            "event_type": "released",
            "effective": "2025-01-15T00:00:00Z",
            "version": "1.0.0",
        }
        create_resp = client.post(base_url, data=payload, content_type="application/json", **headers)
        assert create_resp.status_code == 201
        created = json.loads(create_resp.content)

        detail_url = f"{base_url}/{created['event_id']}"
        response = client.get(detail_url, **headers)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["event_id"] == created["event_id"]

        response_404 = client.get(f"{base_url}/9999", **headers)
        assert response_404.status_code == 404

    def test_component_release_not_found_returns_404(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = "/api/v1/component-releases/nonexistent_id/cle/events"

        response = client.get(url, **headers)
        assert response.status_code == 404

    def test_create_and_list_support_definitions(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_component_release: ComponentRelease,
    ) -> None:
        client, token = authenticated_api_client
        headers = get_api_headers(token)
        url = f"/api/v1/component-releases/{sample_component_release.pk}/cle/support-definitions"

        payload = {
            "support_id": "standard",
            "description": "Standard support tier",
        }
        response = client.post(url, data=payload, content_type="application/json", **headers)
        assert response.status_code == 201, response.content

        response_list = client.get(url, **headers)
        assert response_list.status_code == 200
        items = json.loads(response_list.content)
        assert len(items) == 1
        assert items[0]["support_id"] == "standard"

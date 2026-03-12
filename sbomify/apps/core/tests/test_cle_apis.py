from __future__ import annotations

import json
from typing import Any, Generator

import pytest
from django.test import Client

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.models import Product
from sbomify.apps.teams.models import Member


@pytest.fixture
def sample_billing_plan() -> Generator[BillingPlan, Any, None]:
    plan = BillingPlan.objects.create(
        key="test_cle_plan",
        name="Test CLE Plan",
        description="Plan for CLE API tests",
        max_products=10,
        max_projects=10,
        max_components=10,
    )
    yield plan
    plan.delete()


@pytest.fixture
def sample_product(
    sample_team_with_owner_member: Member,
    sample_billing_plan: BillingPlan,
) -> Generator[Product, Any, None]:
    team = sample_team_with_owner_member.team
    team.billing_plan = sample_billing_plan.key
    team.save()

    product = Product(team_id=team.pk, name="CLE test product")
    product.save()

    yield product

    product.delete()


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
        assert response2.status_code == 201

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
        assert create_resp.status_code == 201
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

        # Missing required "version" for released event type
        payload = {
            "event_type": "released",
            "effective": "2025-01-15T00:00:00Z",
        }
        response = client.post(url, data=payload, content_type="application/json", **headers)
        assert response.status_code == 400


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

        # Duplicate
        response2 = client.post(url, data=payload, content_type="application/json", **headers)
        assert response2.status_code == 409

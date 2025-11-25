import json

import pytest
from django.urls import reverse

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.shared_fixtures import get_api_headers


@pytest.mark.django_db
def test_create_component_can_be_global(authenticated_api_client, team_with_business_plan):  # noqa: F811
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    payload = {
        "name": "Workspace SOC2",
        "component_type": "document",
        "is_global": True,
    }

    response = client.post(
        reverse("api-1:create_component"),
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["is_global"] is True

    component = Component.objects.get(id=data["id"])
    assert component.is_global is True
    assert component.component_type == Component.ComponentType.DOCUMENT
    assert component.team == team_with_business_plan


@pytest.mark.django_db
def test_create_global_sbom_is_rejected(authenticated_api_client, team_with_business_plan):  # noqa: F811
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    payload = {
        "name": "Global SBOM",
        "component_type": "sbom",
        "is_global": True,
    }

    response = client.post(
        reverse("api-1:create_component"),
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_patch_component_scope(authenticated_api_client, team_with_business_plan):  # noqa: F811
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    component = Component.objects.create(
        name="Scoped Component",
        team=team_with_business_plan,
        component_type=Component.ComponentType.SBOM,
        is_global=False,
    )

    response = client.patch(
        reverse("api-1:patch_component", kwargs={"component_id": component.id}),
        data=json.dumps({"is_global": True}),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_global"] is True

    component.refresh_from_db()
    assert component.is_global is True


@pytest.mark.django_db
def test_patch_global_sbom_rejected(authenticated_api_client, team_with_business_plan):  # noqa: F811
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    component = Component.objects.create(
        name="SBOM",
        team=team_with_business_plan,
        component_type=Component.ComponentType.SBOM,
        is_global=False,
    )

    response = client.patch(
        reverse("api-1:patch_component", kwargs={"component_id": component.id}),
        data=json.dumps({"is_global": True}),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_put_change_type_to_sbom_rejected_when_global(authenticated_api_client, team_with_business_plan):  # noqa: F811
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    component = Component.objects.create(
        name="Global Doc",
        team=team_with_business_plan,
        component_type=Component.ComponentType.DOCUMENT,
        is_global=True,
        is_public=True,
    )

    payload = {
        "name": component.name,
        "component_type": "sbom",
        "is_public": True,
        "metadata": {},
    }

    response = client.put(
        reverse("api-1:update_component", kwargs={"component_id": component.id}),
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_list_components_returns_scope_flag(authenticated_api_client, team_with_business_plan):  # noqa: F811
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    global_component = Component.objects.create(
        name="Workspace Artifact",
        team=team_with_business_plan,
        component_type=Component.ComponentType.DOCUMENT,
        is_global=True,
        is_public=True,
    )
    scoped_component = Component.objects.create(
        name="Project Scoped",
        team=team_with_business_plan,
        component_type=Component.ComponentType.SBOM,
        is_global=False,
        is_public=True,
    )

    response = client.get(
        reverse("api-1:list_components") + "?page_size=-1",
        **headers,
    )

    assert response.status_code == 200
    items = response.json()["items"]
    by_id = {item["id"]: item for item in items}

    assert by_id[global_component.id]["is_global"] is True
    assert by_id[scoped_component.id]["is_global"] is False

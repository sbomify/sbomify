"""The TEA API's own OpenAPI surface.

Both endpoints 500'd on a plain URL-resolution error and nothing noticed,
because no test ever requested them. They need no fixtures, so there is no
reason not to assert them.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.tea.mappers import TEA_API_VERSION

pytestmark = pytest.mark.django_db

BASE = f"/tea/v{TEA_API_VERSION}/"


@pytest.mark.parametrize("path", ["docs", "openapi.json"])
def test_the_openapi_surface_is_reachable(client: Client, path: str):
    """Guards the namespace shape. Declaring app_name here as well as
    urls_namespace on the NinjaAPI nests "tea" inside itself, so every route
    lands at tea:tea:<name> while django-ninja reverses tea:<name>."""
    response = client.get(f"{BASE}{path}")

    assert response.status_code == 200


def test_the_schema_describes_the_tea_api(client: Client):
    schema = client.get(f"{BASE}openapi.json").json()

    assert "Transparency Exchange API" in schema["info"]["title"]
    assert schema["paths"]


def test_the_route_names_resolve_without_a_doubled_namespace():
    """The direct assertion. A doubled namespace still serves the routes, so
    only reversing catches it."""
    assert reverse("tea:openapi-json").endswith("openapi.json")
    assert reverse("tea:api-root") == BASE

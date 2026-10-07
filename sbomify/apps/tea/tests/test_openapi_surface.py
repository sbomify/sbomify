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


WORKSPACE_BASE = f"/public/DBirHY9Rei/tea/v{TEA_API_VERSION}/"


@pytest.mark.parametrize("path", ["docs", "openapi.json"])
def test_the_openapi_surface_is_reachable_under_a_workspace_key(client: Client, path: str):
    """The same module is mounted a second time under /public/<workspace_key>/.

    Both mounts share the "tea" namespace, so django-ninja's reverse() only
    ever finds the custom-domain pattern -- which has no workspace_key -- and
    this surface 500'd with NoReverseMatch.
    """
    response = client.get(f"{WORKSPACE_BASE}{path}")

    assert response.status_code == 200


def test_the_workspace_scoped_schema_describes_its_own_prefix(client: Client):
    """A schema advertising /tea/... to a caller on /public/<key>/tea/... sends
    them to a 404, so the prefix has to follow the mount."""
    schema = client.get(f"{WORKSPACE_BASE}openapi.json").json()

    assert schema["paths"]
    assert all(route.startswith(WORKSPACE_BASE) for route in schema["paths"]), sorted(schema["paths"])[:3]


def test_the_workspace_scoped_docs_page_points_at_its_own_schema(client: Client):
    body = client.get(f"{WORKSPACE_BASE}docs").content.decode()

    assert f"{WORKSPACE_BASE}openapi.json" in body


def test_the_custom_domain_schema_still_describes_the_bare_prefix(client: Client):
    """The fallback path: no workspace key, so nothing should have moved."""
    schema = client.get(f"{BASE}openapi.json").json()

    assert all(route.startswith(BASE) for route in schema["paths"]), sorted(schema["paths"])[:3]


def test_each_mount_keeps_its_own_prefix_whichever_is_asked_first(client: Client):
    """Both mounts share one NinjaAPI and one docs renderer, so nothing the first
    request derives may stick to them for the next one. Ask in both orders."""
    for base in (WORKSPACE_BASE, BASE, WORKSPACE_BASE):
        paths = client.get(f"{base}openapi.json").json()["paths"]
        docs = client.get(f"{base}docs").content.decode()

        assert paths and all(route.startswith(base) for route in paths), (base, sorted(paths)[:3])
        assert f'"url": "{base}openapi.json"' in docs, base

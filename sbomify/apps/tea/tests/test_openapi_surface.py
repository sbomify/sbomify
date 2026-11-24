"""The TEA API's own OpenAPI surface.

Both endpoints 500'd on a plain URL-resolution error and nothing noticed,
because no test ever requested them. They need no fixtures, so there is no
reason not to assert them.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.tea.mappers import TEA_API_VERSION, TEA_V1_VERSION

pytestmark = pytest.mark.django_db

# Each TEA version is its own NinjaAPI with its own URL namespace.
VERSIONS = pytest.mark.parametrize("version,namespace", [(TEA_API_VERSION, "tea"), (TEA_V1_VERSION, "tea_v1")])
PATHS = pytest.mark.parametrize("path", ["docs", "openapi.json"])


@VERSIONS
@PATHS
def test_the_openapi_surface_is_reachable(client: Client, path: str, version: str, namespace: str):
    """Guards the namespace shape. Declaring app_name here as well as
    urls_namespace on the NinjaAPI nests "tea" inside itself, so every route
    lands at tea:tea:<name> while django-ninja reverses tea:<name>."""
    response = client.get(f"/tea/v{version}/{path}")

    assert response.status_code == 200


@VERSIONS
def test_the_schema_describes_the_tea_api(client: Client, version: str, namespace: str):
    schema = client.get(f"/tea/v{version}/openapi.json").json()

    assert "Transparency Exchange API" in schema["info"]["title"]
    assert schema["info"]["version"] == version
    assert schema["paths"]


@VERSIONS
def test_the_route_names_resolve_without_a_doubled_namespace(version: str, namespace: str):
    """The direct assertion. A doubled namespace still serves the routes, so
    only reversing catches it."""
    assert reverse(f"{namespace}:openapi-json").endswith("openapi.json")
    assert reverse(f"{namespace}:api-root") == f"/tea/v{version}/"


@VERSIONS
@PATHS
def test_the_openapi_surface_is_reachable_under_a_workspace_key(
    client: Client, path: str, version: str, namespace: str
):
    """The same surface on the workspace-key mount.

    The API is mounted twice, and django-ninja reverses its own routes against
    the single ``urls_namespace`` it was given. That name resolves to the
    custom-domain mount, which takes no workspace_key, so both endpoints 500'd
    here while the custom-domain ones stayed green.
    """
    response = client.get(f"/public/DBirHY9Rei/tea/v{version}/{path}")

    assert response.status_code == 200


@VERSIONS
def test_the_workspace_schema_points_back_at_the_workspace_mount(client: Client, version: str, namespace: str):
    """The prefix has to carry the workspace key, or every documented path is wrong.

    Every path, not merely one of them. The bug this covers is a reversal
    against the wrong ``urls_namespace``, and nothing makes that failure
    all-or-nothing -- a schema mixing correctly and incorrectly prefixed paths
    is exactly what a partial regression would look like, and it is still a
    schema a client cannot use.
    """
    workspace_base = f"/public/DBirHY9Rei/tea/v{version}/"
    schema = client.get(f"{workspace_base}openapi.json").json()
    paths = schema["paths"]

    # A schema that documents nothing would satisfy the assertion below.
    assert paths, "the workspace mount documented no paths at all"

    wrong = [path for path in paths if not path.startswith(workspace_base)]
    assert not wrong, f"paths not on the workspace mount: {wrong}"

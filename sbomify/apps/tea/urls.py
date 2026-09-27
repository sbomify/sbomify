"""
TEA (Transparency Exchange API) URL configuration.

This module provides URL patterns for the TEA API endpoints.
The actual API routes are handled by Django Ninja router.
"""

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.urls import URLPattern, URLResolver, path, reverse
from ninja import NinjaAPI
from ninja.openapi.docs import Swagger

from sbomify.apis import UTCZRenderer
from sbomify.apps.tea.apis import router
from sbomify.apps.tea.mappers import TEA_API_VERSION
from sbomify.logging import getLogger

log = getLogger(__name__)

# Deliberately no ``app_name``. ``tea_api.urls`` already carries the "tea"
# namespace from ``urls_namespace``, and declaring one here too nests it inside
# itself: every route ends up at ``tea:tea:<name>`` while django-ninja reverses
# ``tea:<name>``, which 500s /docs and /openapi.json with NoReverseMatch.

# This URLconf is mounted twice: at ``/tea/v{version}/`` for custom domains, and
# at ``/public/<workspace_key>/tea/v{version}/`` for the shared host. Django
# keeps one entry per namespace, so both mounts declaring "tea" left the
# workspace-scoped one unreachable by name -- ``/docs`` and ``/openapi.json``
# under it 500'd on ``Reverse for 'api-root' with keyword arguments
# {'workspace_key': ...} not found``, since the surviving "tea" pattern takes no
# workspace_key. Each mount therefore gets its own namespace, and the two
# reversing call sites below pick the one matching the params they were handed.
ROOT_NAMESPACE = "tea"
WORKSPACE_MOUNT_NAMESPACE = "tea-workspace"
# ``sbomify.apps.core.urls`` carries the workspace mount and is itself namespaced
# "core", so reversing has to name the whole path down to it.
WORKSPACE_URL_NAMESPACE = f"core:{WORKSPACE_MOUNT_NAMESPACE}"


def _reverse_for_mount(url_name: str, path_params: dict[str, Any]) -> str:
    """Reverse ``url_name`` against whichever mount takes ``path_params``."""
    namespace = WORKSPACE_URL_NAMESPACE if "workspace_key" in path_params else ROOT_NAMESPACE
    return reverse(f"{namespace}:{url_name}", kwargs=path_params)


class _MountAwareSwagger(Swagger):
    """Points the Swagger page at the openapi.json of the mount serving it."""

    def get_openapi_url(self, api: NinjaAPI, path_params: dict[str, Any]) -> str:
        return _reverse_for_mount("openapi-json", path_params)


class _MountAwareNinjaAPI(NinjaAPI):
    """Prefixes the generated schema with the mount the request came in on."""

    def get_root_path(self, path_params: dict[str, Any]) -> str:
        return _reverse_for_mount("api-root", path_params)


# Create a dedicated NinjaAPI instance for TEA
# This allows TEA to have its own OpenAPI docs
tea_api = _MountAwareNinjaAPI(
    renderer=UTCZRenderer(),
    title="Transparency Exchange API (TEA)",
    version=TEA_API_VERSION,
    description="""
Transparency Exchange API (TEA) for sbomify.

This API provides standardized access to software transparency information
including products, releases, components, and security artifacts.

## Authentication

All TEA endpoints are public and do not require authentication.
Access is scoped to public workspace content only.

## Workspace Resolution

Endpoints can be accessed via:
- **Custom domains**: `https://trust.example.com/tea/v{version}/...`
- **Workspace key**: `https://app.sbomify.com/public/{workspace_key}/tea/v{version}/...`
    """.strip(),
    openapi_url="/openapi.json",
    docs_url="/docs",
    urls_namespace=ROOT_NAMESPACE,
    docs=_MountAwareSwagger(),
)


@tea_api.exception_handler(Exception)
def tea_global_exception_handler(request: HttpRequest, exc: Exception) -> HttpResponse:
    """Catch unhandled exceptions and return a generic 500 response."""
    log.exception("Unhandled TEA API error: %s", exc)
    return tea_api.create_response(request, {"error": "Internal server error"}, status=500)


tea_api.add_router("/", router)


# Read once and only once: ``NinjaAPI.urls`` registers the API as a side effect
# and refuses a second read with "Router@'/' has already been attached". The
# triple it hands back is what ``path()`` accepts in place of ``include()``, and
# re-labelling its namespace is what gives each mount its own entry in Django's
# namespace dictionary instead of the second overwriting the first.
_TEA_PATTERNS, _TEA_APP_NAME, _ = tea_api.urls


def _mount(namespace: str) -> list[URLPattern | URLResolver]:
    """One mount of the TEA API, named under ``namespace``.

    The pattern objects are shared between mounts, as they are whenever a
    URLconf is included twice; Django builds its reverse dictionary per
    resolver, so each mount reverses to its own prefix.
    """
    return [path("", (_TEA_PATTERNS, _TEA_APP_NAME, namespace))]


urlpatterns = _mount(ROOT_NAMESPACE)

# Mounted under ``/public/<workspace_key>/`` by ``sbomify.apps.core.urls``.
workspace_urlpatterns = _mount(WORKSPACE_MOUNT_NAMESPACE)

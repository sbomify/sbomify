"""
TEA (Transparency Exchange API) URL configuration.

This module provides URL patterns for the TEA API endpoints.
The actual API routes are handled by Django Ninja router.
"""

from django.http import HttpRequest, HttpResponse
from django.urls import NoReverseMatch, path, reverse
from ninja import NinjaAPI
from ninja.openapi.docs import Swagger
from ninja.types import DictStrAny

from sbomify.apis import UTCZRenderer
from sbomify.apps.tea.apis import router
from sbomify.apps.tea.mappers import TEA_API_VERSION
from sbomify.logging import getLogger

log = getLogger(__name__)

# This module is included twice: at ``tea/v<version>/`` for custom domains, and at
# ``public/<workspace_key>/tea/v<version>/`` inside the "core" namespace. django-ninja
# reverses its own /docs and /openapi.json routes against the one ``urls_namespace``
# the API was built with, and that name only ever resolves to the custom-domain mount,
# which takes no workspace_key. Requests arriving through the workspace-key mount
# therefore 500'd with NoReverseMatch. Try each mount and take the one that accepts
# the path parameters the request actually carries: with a workspace_key only the
# nested mount matches, without one only the top-level mount does, so the choice is
# never ambiguous.
TEA_URL_NAMESPACES: tuple[str, ...] = ("tea", "core:tea")


def reverse_tea_url(route_name: str, path_params: DictStrAny) -> str:
    """Reverse a TEA route against whichever mount the request came through."""
    for namespace in TEA_URL_NAMESPACES:
        try:
            return reverse(f"{namespace}:{route_name}", kwargs=path_params)
        except NoReverseMatch:
            continue

    raise NoReverseMatch(f"Reverse for {route_name!r} with {path_params!r} not found in any of {TEA_URL_NAMESPACES!r}.")


class MountAwareSwagger(Swagger):
    """Point the docs page at the openapi.json of the mount serving it."""

    def get_openapi_url(self, api: NinjaAPI, path_params: DictStrAny) -> str:
        return reverse_tea_url("openapi-json", path_params)


class MountAwareNinjaAPI(NinjaAPI):
    """Prefix documented paths with the mount serving the schema."""

    def get_root_path(self, path_params: DictStrAny) -> str:
        return reverse_tea_url("api-root", path_params)


# Deliberately no ``app_name``. ``tea_api.urls`` already carries the "tea"
# namespace from ``urls_namespace``, and declaring one here too nests it inside
# itself: every route ends up at ``tea:tea:<name>`` while django-ninja reverses
# ``tea:<name>``, which 500s /docs and /openapi.json with NoReverseMatch.

# Create a dedicated NinjaAPI instance for TEA
# This allows TEA to have its own OpenAPI docs
tea_api = MountAwareNinjaAPI(
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
    docs=MountAwareSwagger(),
    urls_namespace="tea",
)


@tea_api.exception_handler(Exception)
def tea_global_exception_handler(request: HttpRequest, exc: Exception) -> HttpResponse:
    """Catch unhandled exceptions and return a generic 500 response."""
    log.exception("Unhandled TEA API error: %s", exc)
    return tea_api.create_response(request, {"error": "Internal server error"}, status=500)


tea_api.add_router("/", router)

urlpatterns = [
    path("", tea_api.urls),
]

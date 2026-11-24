"""
TEA (Transparency Exchange API) URL configuration.

This module provides URL patterns for the TEA API endpoints.
The actual API routes are handled by Django Ninja router.
"""

from django.http import HttpRequest, HttpResponse
from django.urls import NoReverseMatch, path, reverse
from ninja import NinjaAPI
from ninja.errors import ValidationError
from ninja.openapi.docs import Swagger
from ninja.types import DictStrAny

from sbomify.apis import UTCZRenderer
from sbomify.apps.tea.apis import router
from sbomify.apps.tea.apis_v1 import router as router_v1
from sbomify.apps.tea.mappers import TEA_API_VERSION, TEA_V1_VERSION
from sbomify.backend_outage import unavailable_backend
from sbomify.logging import getLogger

log = getLogger(__name__)


# Each TEA API is included twice: at ``tea/v<version>/`` for custom domains, and at
# ``public/<workspace_key>/tea/v<version>/`` inside the "core" namespace. django-ninja
# reverses its own /docs and /openapi.json routes against the one ``urls_namespace``
# the API was built with, and that name only ever resolves to the custom-domain mount,
# which takes no workspace_key. Requests arriving through the workspace-key mount
# therefore 500'd with NoReverseMatch. Try each mount and take the one that accepts
# the path parameters the request actually carries: with a workspace_key only the
# nested mount matches, without one only the top-level mount does, so the choice is
# never ambiguous.
def reverse_tea_url(route_name: str, path_params: DictStrAny, namespace: str = "tea") -> str:
    """Reverse a route of the TEA API named ``namespace`` against whichever mount the request came through."""
    namespaces = (namespace, f"core:{namespace}")
    for candidate in namespaces:
        try:
            return reverse(f"{candidate}:{route_name}", kwargs=path_params)
        except NoReverseMatch:
            continue

    raise NoReverseMatch(f"Reverse for {route_name!r} with {path_params!r} not found in any of {namespaces!r}.")


class MountAwareSwagger(Swagger):
    """Point the docs page at the openapi.json of the mount serving it."""

    def get_openapi_url(self, api: NinjaAPI, path_params: DictStrAny) -> str:
        return reverse_tea_url("openapi-json", path_params, api.urls_namespace or "tea")


class MountAwareNinjaAPI(NinjaAPI):
    """Prefix documented paths with the mount serving the schema."""

    def get_root_path(self, path_params: DictStrAny) -> str:
        return reverse_tea_url("api-root", path_params, self.urls_namespace or "tea")


# Deliberately no ``app_name``. ``tea_api.urls`` already carries the "tea"
# namespace from ``urls_namespace``, and declaring one here too nests it inside
# itself: every route ends up at ``tea:tea:<name>`` while django-ninja reverses
# ``tea:<name>``, which 500s /docs and /openapi.json with NoReverseMatch.

_DESCRIPTION = """
Transparency Exchange API (TEA) {version} for sbomify.

This API provides standardized access to software transparency information
including products, releases, components, and security artifacts.

## Authentication

All TEA endpoints are public and do not require authentication.
Access is scoped to public workspace content only.

## Workspace Resolution

Endpoints can be accessed via:
- **Custom domains**: `https://trust.example.com/tea/v{version}/...`
- **Workspace key**: `https://app.sbomify.com/public/{{workspace_key}}/tea/v{version}/...`
""".strip()


def _tea_api(version: str, urls_namespace: str) -> MountAwareNinjaAPI:
    """A dedicated NinjaAPI per TEA version, so each has its own OpenAPI docs."""
    return MountAwareNinjaAPI(
        renderer=UTCZRenderer(),
        title="Transparency Exchange API (TEA)",
        version=version,
        description=_DESCRIPTION.format(version=version),
        openapi_url="/openapi.json",
        docs_url="/docs",
        docs=MountAwareSwagger(),
        urls_namespace=urls_namespace,
    )


tea_api = _tea_api(TEA_API_VERSION, "tea")
tea_v1_api = _tea_api(TEA_V1_VERSION, "tea_v1")


@tea_api.exception_handler(Exception)
def tea_global_exception_handler(request: HttpRequest, exc: Exception) -> HttpResponse:
    """Catch unhandled exceptions and return a generic 500 response.

    A backend outage is re-raised, so ``BackendUnavailableMiddleware`` answers
    it with a 503 the client can retry, like every other endpoint.
    """
    if unavailable_backend(exc) is not None:
        raise exc
    log.exception("Unhandled TEA API error: %s", exc)
    return tea_api.create_response(request, {"error": "Internal server error"}, status=500)


tea_v1_api.exception_handler(Exception)(tea_global_exception_handler)


@tea_v1_api.exception_handler(ValidationError)
def tea_v1_invalid_request(request: HttpRequest, exc: ValidationError) -> HttpResponse:
    """Answer a malformed request with TEA 1.0.0's error body, not ninja's 422."""
    message = "; ".join(f"{'.'.join(map(str, error['loc'][1:]))}: {error['msg']}" for error in exc.errors)
    return tea_v1_api.create_response(request, {"error": "INVALID_REQUEST", "message": message}, status=400)


tea_api.add_router("/", router)
tea_v1_api.add_router("/", router_v1)

urlpatterns = [
    path("", tea_api.urls),
]

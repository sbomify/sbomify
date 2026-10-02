"""
TEA (Transparency Exchange API) URL configuration.

This module provides URL patterns for the TEA API endpoints.
The actual API routes are handled by Django Ninja router.
"""

from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable

from django.http import HttpRequest, HttpResponse
from django.urls import path
from ninja import NinjaAPI
from ninja.openapi.docs import Swagger
from ninja.types import DictStrAny

from sbomify.apis import UTCZRenderer
from sbomify.apps.tea.apis import router
from sbomify.apps.tea.mappers import TEA_API_VERSION
from sbomify.logging import getLogger

log = getLogger(__name__)

# Deliberately no ``app_name``. ``tea_api.urls`` already carries the "tea"
# namespace from ``urls_namespace``, and declaring one here too nests it inside
# itself: every route ends up at ``tea:tea:<name>`` while django-ninja reverses
# ``tea:<name>``, which 500s /docs and /openapi.json with NoReverseMatch.

# This module is included at two prefixes -- ``/tea/v{version}/`` for custom
# domains and ``/public/<workspace_key>/tea/v{version}/`` for everything else --
# and both carry the same "tea" namespace. See ``_MountAwareNinjaAPI`` for what
# that costs and how the docs surface works around it.
_docs_request: ContextVar[HttpRequest | None] = ContextVar("tea_docs_request", default=None)


def _remember_request(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Hand the request down to ``get_root_path``, which django-ninja calls without one."""

    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        token = _docs_request.set(request)
        try:
            return view(request, *args, **kwargs)
        finally:
            _docs_request.reset(token)

    return wrapper


class _MountAwareNinjaAPI(NinjaAPI):
    """A NinjaAPI that survives being mounted at more than one URL prefix.

    django-ninja derives the schema's path prefix from
    ``reverse(f"{urls_namespace}:api-root")``. Django keeps one resolver per
    namespace, so with two mounts sharing "tea" it only ever reverses the
    custom-domain one -- and that pattern has no place for the
    ``workspace_key`` the other mount supplies, so ``/public/<key>/tea/{v}/docs``
    and ``.../openapi.json`` both 500 with NoReverseMatch.

    The prefix we want is already sitting in the request path, so read it from
    there and keep ``reverse`` as the fallback.
    """

    def get_root_path(self, path_params: DictStrAny) -> str:
        request = _docs_request.get()
        if request is not None:
            for url in (self.openapi_url, self.docs_url):
                leaf = (url or "").lstrip("/")
                if leaf and request.path.endswith(leaf):
                    return request.path[: -len(leaf)]
        return super().get_root_path(path_params)


class _MountAwareSwagger(Swagger):
    """Points the docs page at its own mount's schema, for the same reason."""

    def get_openapi_url(self, api: NinjaAPI, path_params: DictStrAny) -> str:
        leaf = (api.openapi_url or "").lstrip("/")
        return f"{api.get_root_path(path_params)}{leaf}"


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
    docs=_MountAwareSwagger(),
    docs_decorator=_remember_request,
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

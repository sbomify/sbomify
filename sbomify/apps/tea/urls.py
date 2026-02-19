"""
TEA (Transparency Exchange API) URL configuration.

This module provides URL patterns for the TEA API endpoints.
The actual API routes are handled by Django Ninja router.
"""

from django.http import HttpRequest, HttpResponse
from django.urls import path
from ninja import NinjaAPI

from sbomify.apps.tea.apis import router
from sbomify.apps.tea.mappers import TEA_API_VERSION
from sbomify.logging import getLogger

log = getLogger(__name__)

app_name = "tea"

# Create a dedicated NinjaAPI instance for TEA
# This allows TEA to have its own OpenAPI docs
tea_api = NinjaAPI(
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

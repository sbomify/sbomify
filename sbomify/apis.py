import math
from datetime import datetime, timedelta
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpRequest
from django.utils.module_loading import import_string
from ninja import NinjaAPI
from ninja.errors import Throttled
from ninja.renderers import JSONRenderer

from sbomify.api_schema_variants import SchemaVariants
from sbomify.api_versioning import clone_router
from sbomify.apps.access_tokens.throttling import AccessTokenRateThrottle, AnonymousIPRateThrottle
from sbomify.apps.core.schemas import DEFAULT_ERROR_CODE_BY_STATUS

try:
    __version__ = version("sbomify")
except PackageNotFoundError:
    __version__ = "0.2.0"  # Fallback to current version


class _UTCZEncoder(DjangoJSONEncoder):
    """JSON encoder that serializes UTC datetimes with Z suffix per RFC 3339."""

    def default(self, o: Any) -> Any:
        if isinstance(o, datetime) and o.tzinfo is not None and o.utcoffset() == timedelta(0):
            return o.strftime("%Y-%m-%dT%H:%M:%SZ")
        if isinstance(o, Enum):
            return o.value
        return super().default(o)


class UTCZRenderer(JSONRenderer):
    encoder_class = _UTCZEncoder

    def render(self, request: HttpRequest, data: Any, *, response_status: int) -> Any:
        """Fill in ``error_code`` when the view left it out.

        Around two hundred error returns ship a bare ``detail``, so a client
        branching on the code reads null and has to fall back to matching the
        prose, which is not a contract. Deriving it from the status here covers
        every route at once, including ninja's own 422 and the throttle
        handler below, and means a new error cannot ship uncoded. A view that
        names its own code always wins.
        """
        if response_status >= 400 and isinstance(data, dict) and "detail" in data and data.get("error_code") is None:
            if default := DEFAULT_ERROR_CODE_BY_STATUS.get(response_status):
                data = {**data, "error_code": default.value}
        return super().render(request, data, response_status=response_status)


api = NinjaAPI(
    # CSRF protects cookie/session-authenticated requests. Personal Access Token
    # (bearer) clients are exempted by BearerAuthCsrfExemptMiddleware so the API stays
    # usable for programmatic clients (which carry no CSRF cookie and cannot be a CSRF
    # vector). See sbomify/apps/core/middleware.py.
    csrf=True,
    # Two complementary global throttles, because each returns no cache key for
    # the other's population: the token one keys on the AccessToken pk and skips
    # anonymous callers, the anonymous one keys on client IP and skips requests
    # that resolved a token. Together they cover every route, including the
    # auth=None public ones, without decorating each endpoint.
    #
    # A per-operation throttle replaces this whole list rather than adding to
    # it, so any endpoint declaring its own must re-list every global throttle
    # it still wants. The artifact-upload routes are the example: they pass
    # AccessTokenRateThrottle alongside AccessTokenHeavyRateThrottle for that
    # reason, and being PAT-only they have no need of the anonymous one.
    throttle=[AccessTokenRateThrottle(), AnonymousIPRateThrottle()],
    renderer=UTCZRenderer(),
    title="sbomify API",
    version=__version__,
    description="""
A comprehensive API for managing Software Bill of Materials (SBOM) and document artifacts.

## Features

- **Product Management**: Create and organize products with identifiers and external links
- **Component & Artifact Management**: Handle components, SBOMs, and documents with security analysis
- **Release Management**: Tag and organize artifacts by product releases with download capabilities
- **Workspace Collaboration**: Multi-user access with role-based permissions
- **Public & Private Access**: Flexible sharing and access controls with signed URLs for private components
- **Vulnerability Scanning**: Integrated security analysis with OSV database
- **Signed URL Security**: Time-limited, secure access to private components without authentication

## Authentication

This API supports two authentication methods:

- **Session Authentication**: For web application users (login required)
- **Personal Access Tokens**: For programmatic API access (Bearer token in Authorization header)

Most endpoints require authentication. Public endpoints are clearly marked.

## Rate Limiting

API requests are subject to rate limiting to ensure fair usage and system stability.
    """.strip(),
    openapi_url="/openapi.json",
    docs_url="/docs",
    urls_namespace="api-1",
    openapi_extra={
        "info": {
            "contact": {
                "name": "sbomify Support",
                "url": "https://sbomify.com",
                "email": "hello@sbomify.com",
            },
            "license": {
                "name": "Apache 2.0 with Commons Clause",
                "url": "https://raw.githubusercontent.com/sbomify/sbomify/refs/heads/master/LICENSE",
            },
        },
        "tags": [
            {
                "name": "SBOMs",
                "description": "Manage Software Bill of Materials with upload, validation, and security analysis. "
                "SBOMs are automatically scanned for vulnerabilities and compliance.",
            },
            {
                "name": "Documents",
                "description": "Upload and manage document artifacts like security advisories, compliance reports, "
                "and technical documentation associated with your components.",
            },
            {
                "name": "Components",
                "description": "Organize and manage software components that contain SBOMs and documents. "
                "Components provide logical grouping and access control.",
            },
            {
                "name": "Products",
                "description": "Structure your software inventory with products that group components and "
                "are organised by releases.",
            },
            {
                "name": "Releases",
                "description": "Tag and manage product releases with downloadable artifacts and version tracking. "
                "Create public or private releases with secure access controls.",
            },
            {
                "name": "Access Tokens",
                "description": "Manage API authentication tokens for programmatic access to sbomify. "
                "Create and revoke personal access tokens for secure API integration.",
            },
            {
                "name": "Workspaces",
                "description": "Manage workspace settings, members, branding, and collaboration features. "
                "Control access and permissions across your organization.",
            },
            {
                "name": "Billing",
                "description": "Manage subscription plans, usage tracking, and billing operations. "
                "View current plan limits and upgrade options.",
            },
            {
                "name": "Notifications",
                "description": "Retrieve system notifications, alerts, and updates relevant to the "
                "current user and workspace.",
            },
            {
                "name": "Vulnerability Scanning",
                "description": "Configure and manage vulnerability scanning providers including OSV and "
                "Dependency Track. View scanning statistics and configure workspace preferences.",
            },
            {
                "name": "Licensing",
                "description": "Validate license expressions, manage custom licenses, and access "
                "comprehensive license information database.",
            },
            {
                "name": "Internal",
                "description": "Internal endpoints for infrastructure integration. These endpoints are "
                "restricted from external access at the proxy level.",
            },
        ],
    },
)


@api.exception_handler(Throttled)
def _on_throttled(request: Any, exc: Throttled) -> Any:
    """429 with a Retry-After header (#1060); ninja's default HttpError handler drops exc.wait."""
    response = api.create_response(request, {"detail": "Too many requests."}, status=429)
    if exc.wait is not None:
        # Round up (never below 1s) so a fractional wait doesn't truncate to 0 and
        # invite clients to retry too early into the throttle.
        response["Retry-After"] = str(max(1, math.ceil(exc.wait)))
    return response


# Every router is mounted once per API version. v1 is the surface we shipped;
# v2 serves the same views under the vocabulary the product actually uses.
MOUNTS: tuple[tuple[str, str], ...] = (
    ("/sboms", "sbomify.apps.sboms.apis.router"),
    ("/documents", "sbomify.apps.documents.apis.router"),
    ("/", "sbomify.apps.documents.access_apis.router"),
    ("/workspaces", "sbomify.apps.teams.apis.router"),
    ("/", "sbomify.apps.core.apis.router"),
    ("/", "sbomify.apps.core.cle_apis.router"),
    ("/billing", "sbomify.apps.billing.apis.router"),
    ("/notifications", "sbomify.apps.notifications.apis.router"),
    ("/vulnerability-scanning", "sbomify.apps.vulnerability_scanning.apis.router"),
    ("/licensing", "sbomify.apps.licensing.api.router"),
    ("/plugins", "sbomify.apps.plugins.apis.router"),
    ("/compliance", "sbomify.apps.compliance.apis.router"),
    ("/controls", "sbomify.apps.controls.apis.router"),
    ("/internal", "sbomify.apps.teams.apis.internal_router"),
    ("/auth/oidc", "sbomify.apps.oidc.apis.router"),
)

# Both API objects are bound before either is mounted, and that ordering is
# load-bearing rather than tidy. add_router resolves and attaches its routers
# straight away, so the mount below mutates module-level Router objects. If
# anything imported during that mount reaches sbomify.urls, its
# ``from sbomify.apis import api, api_v2`` runs against a half-executed module:
# with api_v2 defined further down, that is an ImportError, python drops
# sbomify.apis from sys.modules, and the retry finds the routers already
# attached and dies with a ConfigError naming /sboms. The real fault is then
# invisible, buried under a cascade blaming the wrong line.

api_v2 = NinjaAPI(
    version="2.0.0",
    urls_namespace="api-2",
    csrf=True,
    throttle=[AccessTokenRateThrottle(), AnonymousIPRateThrottle()],
    renderer=UTCZRenderer(),
    title="sbomify API",
    description=(
        "Version 2 of the sbomify API. Same resources as v1, named the way the "
        "product names them: artifacts rather than sboms, workspaces rather "
        "than teams.\n\n"
        "See /api/v1/docs for the version this replaces."
    ),
)

for _prefix, _dotted in MOUNTS:
    api.add_router(_prefix, _dotted)


# ---------------------------------------------------------------------------
# v2
#
# Same views, same handlers, one vocabulary. The v1 surface grew a prefix named
# for SBOMs that now holds eight artifact types, a path parameter still called
# team_key under a prefix already renamed to /workspaces/, and a resource that
# answers on both /sboms/{id} and /sboms/sbom/{id}. None of that can be fixed
# in place without breaking callers, which is what a second version is for.
# ---------------------------------------------------------------------------

# Prefixes that differ from v1. Anything absent keeps its v1 prefix.
V2_PREFIXES: dict[str, str] = {
    "sbomify.apps.sboms.apis.router": "/artifacts",
}

# Path parameters renamed across every router. The view keeps its own argument
# name; ``clone_router`` wraps it so ninja sees the new one.
V2_PARAM_RENAMES: dict[str, str] = {
    "team_key": "workspace_key",
    "sbom_id": "artifact_id",
}

# Literal segments rewritten inside a router's own paths, applied longest
# first so /artifact/vex is not shortened before /artifact is considered.
V2_SEGMENTS: dict[str, dict[str, str]] = {
    # The prefix already says artifacts, so the segment repeating it goes, and
    # /sbom/{id} collapses onto /{id} where the other verbs already live.
    "sbomify.apps.sboms.apis.router": {"/artifact/": "/", "/sbom/": "/"},
    # Access requests are the last routes still under the old noun.
    "sbomify.apps.documents.access_apis.router": {"/teams/": "/workspaces/"},
    # An artifact's releases are declared in the core router, which mounts at
    # the root, so the /artifacts prefix above never reaches them. Renaming the
    # mount is not enough: a literal path inside another router keeps whatever
    # noun it was written with.
    "sbomify.apps.core.apis.router": {"/sboms/": "/artifacts/"},
}


def _v2_path_rewriter(dotted: str) -> Any:
    segments = V2_SEGMENTS.get(dotted)
    if not segments:
        return None

    def rewrite(path: str) -> str:
        for old, new in sorted(segments.items(), key=lambda kv: -len(kv[0])):
            if path.startswith(old):
                return new + path[len(old) :]
        return path

    return rewrite


# One instance for the whole version, because it caches: the OpenAPI document
# keys components by model name, so a schema converted twice would render as
# two components that only differ by identity.
_v2_schemas = SchemaVariants()

for _prefix, _dotted in MOUNTS:
    api_v2.add_router(
        V2_PREFIXES.get(_dotted, _prefix),
        clone_router(
            import_string(_dotted),
            rewrite_path=_v2_path_rewriter(_dotted),
            param_renames=V2_PARAM_RENAMES,
            rewrite_response=lambda _path, _status, schema: _v2_schemas.response(schema),
            convert_request=_v2_schemas.request,
        ),
    )


# Struck through in /api/v1/docs and flagged in generated clients. This runs
# after the v2 block on purpose: clone_router builds new Operation objects, so
# marking the originals now touches v1 alone. Doing it before the clone would
# have marked v2 deprecated on the day it shipped.
if getattr(settings, "API_V1_SUNSET", None) is not None:
    for _prefix, _router in api._routers:
        for _path_view in _router.path_operations.values():
            for _operation in _path_view.operations:
                _operation.deprecated = True

from importlib.metadata import PackageNotFoundError, version

from ninja import NinjaAPI

try:
    __version__ = version("sbomify")
except PackageNotFoundError:
    __version__ = "0.2.0"  # Fallback to current version

api = NinjaAPI(
    title="sbomify API",
    version=__version__,
    description="""
A comprehensive API for managing Software Bill of Materials (SBOM) and document artifacts.

## Features

- **Product Management**: Create and organize products with identifiers and external links
- **Project Organization**: Manage projects within products for better structure
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
                "name": "Products & Projects",
                "description": "Structure your software inventory with products and projects for better organization "
                "and release management.",
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

api.add_router("/sboms", "sbomify.apps.sboms.apis.router")
api.add_router("/documents", "sbomify.apps.documents.apis.router")
api.add_router("/", "sbomify.apps.documents.access_apis.router")
api.add_router("/workspaces", "sbomify.apps.teams.apis.router")
api.add_router("/", "sbomify.apps.core.apis.router")
api.add_router("/billing", "sbomify.apps.billing.apis.router")
api.add_router("/notifications", "sbomify.apps.notifications.apis.router")
api.add_router("/vulnerability-scanning", "sbomify.apps.vulnerability_scanning.apis.router")
api.add_router("/licensing", "sbomify.apps.licensing.api.router")
api.add_router("/plugins", "sbomify.apps.plugins.apis.router")
api.add_router("/internal", "sbomify.apps.teams.apis.internal_router")

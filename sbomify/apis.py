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
# sbomify API

A comprehensive API for managing Software Bill of Materials (SBOM) and document artifacts.

## Features

- **SBOM Management**: Upload, analyze, and manage CycloneDX and SPDX format SBOMs
- **Document Management**: Store and organize compliance documents, specifications, and reports
- **Vulnerability Scanning**: Integrated security analysis with OSV database
- **Team Collaboration**: Multi-user access with role-based permissions
- **Public & Private Access**: Flexible sharing and access controls
- **Release Management**: Tag and organize artifacts by product releases

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
                "name": "Core",
                "description": "Manage core entities: components, projects, products, and releases. "
                "These endpoints form the foundation of the sbomify platform.",
            },
            {
                "name": "SBOMs",
                "description": "Upload, validate, and manage Software Bill of Materials in CycloneDX and SPDX formats. "
                "Includes vulnerability scanning and analysis.",
            },
            {
                "name": "Documents",
                "description": "Upload and manage document artifacts such as specifications, compliance documents, "
                "manuals, and reports.",
            },
            {
                "name": "Teams",
                "description": "Manage team settings, members, branding, and collaboration features. "
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
                "current user and team.",
            },
            {
                "name": "Licensing",
                "description": "Validate license expressions, manage custom licenses, and access "
                "comprehensive license information database.",
            },
        ],
    },
)

api.add_router("/sboms", "sboms.apis.router")
api.add_router("/documents", "documents.apis.router")
api.add_router("/teams", "teams.apis.router")
api.add_router("/", "core.apis.router")
api.add_router("/billing", "billing.apis.router")
api.add_router("/notifications", "notifications.apis.router")
api.add_router("/licensing", "licensing.api.router")

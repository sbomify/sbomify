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
- **Team Collaboration**: Multi-user access with role-based permissions
- **Public & Private Access**: Flexible sharing and access controls
- **Vulnerability Scanning**: Integrated security analysis with OSV database

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
                "name": "Products",
                "description": "Manage products, their identifiers (CPE, PURL, etc.), and external links. "
                "Products are the top-level organizational unit in sbomify and can contain multiple projects.",
            },
            {
                "name": "Projects",
                "description": "Manage projects within products. Projects help organize components and provide "
                "logical groupings for development workflows and release planning.",
            },
            {
                "name": "Components",
                "description": "Manage components as organizational containers for artifacts. "
                "Components help structure and organize your SBOMs and documents.",
            },
            {
                "name": "Artifacts",
                "description": "Upload and manage SBOMs (Software Bill of Materials) and documents. "
                "Supports CycloneDX/SPDX formats with vulnerability scanning and various document types.",
            },
            {
                "name": "Releases",
                "description": (
                    "Manage product releases and associate artifacts (SBOMs, documents) with specific versions. "
                    "Includes bulk download capabilities and release artifact management."
                ),
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

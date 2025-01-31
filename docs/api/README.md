# API Documentation

## Overview

The Security Artifact Hub API provides RESTful endpoints for managing products, releases, and security artifacts with a focus on maintainability and discoverability.

## Quick Links

- [API Reference](v2-specification.md)
- [Common Use Cases](use-cases.md)
- [Migration Guide](migration.md)
- [Release-Based Architecture](../architecture/releases.md)

## API Versions

### v2 (Current)

The v2 API introduces a product-centric approach with clear separation between products, releases, and artifacts. It provides robust search capabilities and flexible metadata management.

Base URL: `/api/v2/`

### v1 (Legacy)

The v1 API will be maintained for backward compatibility.

Base URL: `/api/v1/`

## Authentication

All API endpoints require authentication using one of:

- Personal Access Token (workspace-scoped)
- Session Authentication (for web UI)

Each token is scoped to a specific workspace, and all API operations are performed within that workspace's context.

## Core Resources

### Workspace

```bash
# Workspace Management
GET    /workspace                # Get current workspace details
PATCH  /workspace               # Update workspace settings
```

### Products

```bash
# Product Management
GET    /products                # List products in current workspace
POST   /products                # Create product
GET    /products/{id}           # Get product details
PATCH  /products/{id}           # Update product
DELETE /products/{id}           # Delete product
```

### Releases

```bash
# Release Management
GET    /products/{id}/releases        # List releases
POST   /products/{id}/releases        # Create release
GET    /products/{id}/releases/{ver}  # Get release details
PATCH  /products/{id}/releases/{ver}  # Update release
DELETE /products/{id}/releases/{ver}  # Delete release
```

### Artifacts

```bash
# Artifact Management
POST   /artifacts                    # Create artifact
GET    /artifacts/{id}               # Get artifact details
PATCH  /artifacts/{id}               # Update artifact
DELETE /artifacts/{id}               # Delete artifact

# Release Associations
POST   /products/{id}/releases/{ver}/artifacts/{artifact_id}  # Associate artifact
DELETE /products/{id}/releases/{ver}/artifacts/{artifact_id}  # Remove association
GET    /products/{id}/releases/{ver}/artifacts                # List artifacts
```

## Search Capabilities

```bash
# Product Search
GET /search/products
    ?q=search_term          # Full-text search
    ?category=string        # Filter by category
    ?tags=tag1,tag2        # Filter by tags
    ?lifecycle=active      # Filter by lifecycle status

# Release Search
GET /search/releases
    ?product_id=uuid       # Filter by product
    ?version=1.0.0        # Filter by version
    ?status=published     # Filter by status
    ?channel=stable       # Filter by channel

# Artifact Search
GET /search/artifacts
    ?type=sbom,vex        # Filter by type
    ?format=cyclonedx     # Filter by format
    ?product_id=uuid      # Filter by product
    ?release_version=1.0.0 # Filter by release
```

## Request/Response Examples

### Create Product

```http
POST /api/v2/products
Content-Type: application/json

{
    "name": "Example Product",
    "description": "Product description",
    "identifiers": {
        "purl": "pkg:supplier/example@1.0.0"
    },
    "metadata": {
        "category": "application",
        "tags": ["web", "security"],
        "lifecycle_status": "active"
    }
}

Response:
{
    "id": "uuid",
    "name": "Example Product",
    "created_at": "2024-01-23T12:00:00Z"
}
```

### Create Release

```http
POST /api/v2/products/{id}/releases
Content-Type: application/json

{
    "version": "1.0.0",
    "status": "draft",
    "metadata": {
        "release_type": "major",
        "release_notes": "Initial release",
        "distribution": {
            "channel": "stable"
        }
    }
}

Response:
{
    "product_id": "uuid",
    "version": "1.0.0",
    "created_at": "2024-01-23T12:00:00Z"
}
```

## Error Handling

All errors follow a consistent format:

```json
{
    "error": {
        "code": "ERROR_CODE",
        "message": "Human readable message",
        "details": {
            // Additional error context
        }
    }
}
```

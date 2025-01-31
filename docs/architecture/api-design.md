# API Design

## Overview

This document details the API design for our release-based architecture, including endpoints, request/response formats, and authentication.

## Base URL Structure

```bash
/api/v2/                    # Base API path
    products/               # Product management
        {id}/projects/      # Projects under product
    projects/              # Project operations
        {id}/components/   # Components under project
    versions/              # Version management (product-component mapping)
    artifacts/             # Artifact management
```

## Authentication

All endpoints require authentication using one of:

- Bearer token (workspace-scoped)
- API key (workspace-scoped)
- Session cookie (for browser-based access)

All tokens are scoped to a specific workspace, and operations are performed within that workspace's context.

## Endpoints

### Product Management

#### List Products

```http
GET /api/v2/products

Query Parameters:
- q (optional): Search by name
- category (optional): Filter by category
- tags (optional): Filter by tags
- lifecycle_status (optional): Filter by status

Response:
{
    "items": [
        {
            "id": "uuid",
            "name": "Product Name",
            "description": "Product description",
            "metadata": {
                "category": "string",
                "tags": ["tag1", "tag2"],
                "lifecycle_status": "active"
            }
        }
    ],
    "total": 100,
    "page": 1,
    "limit": 20
}
```

### Project Management

#### List Projects

```http
GET /api/v2/products/{product_id}/projects

Query Parameters:
- q (optional): Search by name
- type (optional): Filter by type
- status (optional): Filter by status
- page (optional): Page number
- limit (optional): Items per page

Response:
{
    "items": [
        {
            "id": "uuid",
            "name": "Project Name",
            "product_id": "uuid",
            "metadata": {
                "type": "application",
                "status": "active",
                "tags": ["tag1", "tag2"]
            }
        }
    ],
    "total": 100,
    "page": 1,
    "limit": 20
}
```

#### Create Project

```http
POST /api/v2/products/{product_id}/projects

Request:
{
    "name": "Project Name",
    "description": "Project description",
    "metadata": {
        "type": "application",
        "status": "active",
        "tags": ["tag1", "tag2"]
    }
}

Response:
{
    "id": "uuid",
    "name": "Project Name",
    "product_id": "uuid",
    "metadata": {
        "type": "application",
        "status": "active",
        "tags": ["tag1", "tag2"]
    },
    "created_at": "2024-01-01T00:00:00Z"
}
```

### Release Management

#### Create Release

```http
POST /api/v1/projects/{id}/releases

Request:
{
    "version": "1.0.0",
    "status": "draft",
    "metadata": {
        "release_notes": "Initial release",
        "release_type": "major"
    }
}

Response:
{
    "id": "uuid",
    "version": "1.0.0",
    "status": "draft",
    "release_date": null,
    "metadata": { ... },
    "created_at": "2024-01-01T00:00:00Z"
}
```

#### Update Release Status

```http
PATCH /api/v1/projects/{id}/releases/{version}

Request:
{
    "status": "released",
    "metadata": {
        "approvers": ["user1", "user2"]
    }
}

Response:
{
    "id": "uuid",
    "version": "1.0.0",
    "status": "released",
    "release_date": "2024-01-01T00:00:00Z",
    "metadata": { ... },
    "updated_at": "2024-01-01T00:00:00Z"
}
```

### Artifact Management

#### Add Artifact

```http
POST /api/v1/projects/{id}/releases/{version}/artifacts

Request:
{
    "type": "sbom",
    "format": "cyclonedx",
    "content": { ... },
    "metadata": {
        "generator": {
            "name": "tool-name",
            "version": "1.0.0"
        }
    }
}

Response:
{
    "id": "uuid",
    "type": "sbom",
    "format": "cyclonedx",
    "metadata": { ... },
    "created_at": "2024-01-01T00:00:00Z"
}
```

#### List Artifacts

```http
GET /api/v1/projects/{id}/releases/{version}/artifacts

Query Parameters:
- type (optional): Filter by type
- format (optional): Filter by format
- page (optional): Page number
- limit (optional): Items per page

Response:
{
    "items": [
        {
            "id": "uuid",
            "type": "sbom",
            "format": "cyclonedx",
            "metadata": { ... },
            "created_at": "2024-01-01T00:00:00Z"
        }
    ],
    "total": 10,
    "page": 1,
    "limit": 20
}
```

### Artifacts

```bash
# Artifact Management
POST   /artifacts                    # Create new artifact
GET    /artifacts/{id}               # Get artifact details
PATCH  /artifacts/{id}               # Update artifact
DELETE /artifacts/{id}               # Delete artifact

# Artifact Relationships
POST   /artifacts/{id}/relationships # Create relationship
GET    /artifacts/{id}/relationships # List relationships
DELETE /artifacts/{id}/relationships/{rel-id} # Remove relationship

# Release Associations
POST   /releases/{version}/artifacts/{id}     # Associate artifact with release
DELETE /releases/{version}/artifacts/{id}     # Remove artifact from release
GET    /releases/{version}/artifacts          # List artifacts in release
```

### Example: Creating and Associating an Artifact

```http
# 1. Create the artifact
POST /api/v2/artifacts
Content-Type: application/json

{
    "type": "sbom",
    "format": "cyclonedx",
    "content": { ... }
}

Response:
{
    "id": "artifact-uuid",
    "type": "sbom",
    "format": "cyclonedx",
    "created_at": "2024-01-23T12:00:00Z"
}

# 2. Associate with a release
POST /api/v2/releases/1.0.0/artifacts/artifact-uuid

Response:
{
    "release_version": "1.0.0",
    "artifact_id": "artifact-uuid",
    "association_type": "primary",
    "created_at": "2024-01-23T12:00:00Z"
}
```

### Example: Creating Related Artifacts

```http
# 1. Create SBOM
POST /api/v2/artifacts
{
    "type": "sbom",
    "format": "cyclonedx",
    "content": { ... }
}

# 2. Create VEX that references the SBOM
POST /api/v2/artifacts
{
    "type": "vex",
    "format": "csaf",
    "content": { ... }
}

# 3. Create relationship between VEX and SBOM
POST /api/v2/artifacts/{vex-id}/relationships
{
    "type": "references",
    "target_id": "sbom-id",
    "metadata": {
        "reason": "vulnerability_statement"
    }
}

# 4. Associate both with a release
POST /api/v2/releases/1.0.0/artifacts/vex-id
POST /api/v2/releases/1.0.0/artifacts/sbom-id
```

### Search

```bash
# Search artifacts
GET /search/artifacts
    ?type=sbom,vex           # Filter by type
    ?format=cyclonedx        # Filter by format
    ?release_version=1.0.0   # Filter by release version
    ?has_relationship=vex    # Filter by relationship type

# Search relationships
GET /search/relationships
    ?source_type=vex        # Filter by source artifact type
    ?target_type=sbom       # Filter by target artifact type
    ?relationship_type=references  # Filter by relationship type
```

## Search and Discovery

### Search Releases

```http
POST /api/v1/search/releases

Request:
{
    "query": {
        "project_id": "uuid",
        "version_pattern": "1.*",
        "status": ["draft", "released"],
        "date_range": {
            "start": "2024-01-01",
            "end": "2024-12-31"
        }
    },
    "sort": [
        {"field": "release_date", "order": "desc"}
    ],
    "page": 1,
    "limit": 20
}

Response:
{
    "items": [...],
    "total": 100,
    "page": 1,
    "limit": 20
}
```

### Search Artifacts

```http
POST /api/v1/search/artifacts

Request:
{
    "query": {
        "type": ["sbom", "vex"],
        "format": "cyclonedx",
        "content": {
            "components": {
                "name": "package-name"
            }
        }
    },
    "include": ["metadata", "relationships"],
    "sort": [
        {"field": "created_at", "order": "desc"}
    ]
}
```

## Error Handling

All errors follow standard HTTP status codes with detailed messages:

```http
400 Bad Request
{
    "error": "validation_error",
    "message": "Invalid request format",
    "details": {
        "field": ["error message"]
    }
}

404 Not Found
{
    "error": "not_found",
    "message": "Resource not found",
    "resource_type": "release"
}

409 Conflict
{
    "error": "conflict",
    "message": "Version already exists",
    "details": {
        "version": "1.0.0"
    }
}
```

## Rate Limiting

```http
X-RateLimit-Limit: 5000
X-RateLimit-Remaining: 4999
X-RateLimit-Reset: 1640995200
```

## Pagination

All list endpoints support pagination:

```http
Link: <https://api.../projects?page=2>; rel="next",
      <https://api.../projects?page=10>; rel="last"
X-Total-Count: 195
```

## Versioning

The API is versioned through:

1. URL path (/api/v1/)
2. Accept header
3. Content-Type header

## Best Practices

1. **Request Validation**
   - Validate all input
   - Provide clear error messages
   - Use appropriate status codes
   - Include request IDs

2. **Response Format**
   - Consistent structure
   - Include metadata
   - Support pagination
   - Enable filtering

3. **Performance**
   - Cache responses
   - Batch operations
   - Optimize queries
   - Monitor usage

```text
End of document
```

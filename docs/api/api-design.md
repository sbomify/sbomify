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
            "metadata": { ... }
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

// ... rest of the file with updated examples ...

# API Migration Guide

## Overview

This guide details the changes between V1 and V2 APIs and provides guidance for migrating existing integrations.

## Key Changes

### 1. Teams to Workspaces Migration

V1:

- Team-based organization with `team_key` parameter
- Global API tokens
- Team-specific resources
- Public status management per item

V2:

- Workspace-based organization
- Workspace-scoped tokens
- All operations within workspace context
- Simplified URL structure
- Global visibility controls

Key differences:

- "Teams" are now called "Workspaces"
- API tokens are scoped to a specific workspace
- No need to specify workspace in URLs (implicit from token)
- Clearer separation of concerns
- Unified visibility management

### 2. Resource Hierarchy

V1:

```text
Team
├── Products
├── Projects
└── Components
```

V2:

```text
Product
└── Project
    └── Component
```

With Versions as a special mapping between Products and Component artifacts.

### 3. SBOM Management

V1:

```http
# Upload CycloneDX SBOM
POST /api/v1/sboms/artifact/cyclonedx/{component_id}
Content-Type: application/json

{
    "content": {}  # CycloneDX format
}

# Upload SPDX SBOM
POST /api/v1/sboms/artifact/spdx/{component_id}
Content-Type: application/json

{
    "content": {}  # SPDX format
}

# Get component metadata
GET /api/v1/sboms/component/{component_id}/meta
```

V2:

```http
# 1. Create artifact
POST /api/v2/artifacts
{
    "type": "sbom",
    "format": "cyclonedx",
    "content": {}
}

# 2. Create release
POST /api/v2/products/{product_id}/releases
{
    "version": "1.0.0",
    "status": "draft"
}

# 3. Associate artifact with release
POST /api/v2/products/{product_id}/releases/{version}/artifacts/{artifact_id}
```

### 4. Enhanced Metadata

V1:

```json
{
    "component_id": "uuid",
    "metadata": {
        "name": "string",
        "url": "string",
        "supplier": {
            "name": "string",
            "url": "string",
            "address": "string",
            "contacts": []
        }
    }
}
```

V2:

```json
{
    "product": {
        "id": "uuid",
        "name": "string",
        "metadata": {
            "category": "string",
            "tags": ["string"],
            "lifecycle_status": "string"
        }
    },
    "release": {
        "version": "string",
        "metadata": {
            "release_type": "string",
            "distribution": {
                "channel": "string"
            }
        }
    },
    "artifact": {
        "id": "uuid",
        "type": "string",
        "format": "string",
        "metadata": {
            "validation": {
                "status": "string"
            }
        }
    }
}
```

### 5. Public Status Management

V1:

```http
# Get item public status
GET /api/v1/sboms/{item_type}/{item_id}/public_status

# Update item public status
PATCH /api/v1/sboms/{item_type}/{item_id}/public_status
```

V2:

```http
# Get product visibility
GET /api/v2/products/{product_id}/visibility

# Update product visibility
PATCH /api/v2/products/{product_id}/visibility
```

## Migration Steps

1. **Update Authentication**
   - Generate workspace-scoped tokens
   - Update token management in your applications
   - Remove workspace IDs from API calls

2. **Update Resource Structure**
   - Map existing components to products and projects
   - Update artifact associations
   - Implement release management

3. **Update SBOM Management**
   - Use new artifact endpoints
   - Implement release-based versioning
   - Update metadata structure

4. **Update Visibility Controls**
   - Migrate from item-specific public status to product-level visibility
   - Update access control logic

## Examples

### Migrating SBOM Upload

```python
# V1
def upload_sbom_v1(component_id, content):
    response = requests.post(
        f"/api/v1/sboms/artifact/cyclonedx/{component_id}",
        json=content
    )
    return response.json()

# V2
def upload_sbom_v2(product_id, version, content):
    # Create artifact
    artifact_response = requests.post(
        "/api/v2/artifacts",
        json={
            "type": "sbom",
            "format": "cyclonedx",
            "content": content
        }
    )
    artifact_id = artifact_response.json()["id"]

    # Associate with release
    association_response = requests.post(
        f"/api/v2/products/{product_id}/releases/{version}/artifacts/{artifact_id}"
    )
    return association_response.json()
```

### Using New Visibility Controls

```python
# V1 - Item-specific public status
def get_public_status_v1(item_type, item_id):
    return requests.get(f"/api/v1/sboms/{item_type}/{item_id}/public_status")

# V2 - Product-level visibility
def get_visibility_v2(product_id):
    return requests.get(f"/api/v2/products/{product_id}/visibility")
```

## Timeline

1. **Current Phase**
   - Both V1 and V2 APIs available
   - V2 recommended for new integrations

2. **Future**
   - V1 maintenance mode
   - 12-month notice before deprecation

## Support

Need help migrating? Contact us:

- GitHub Issues
- Documentation Updates

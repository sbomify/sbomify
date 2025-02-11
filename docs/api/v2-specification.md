# V2 API Specification

## Core Resources

### Products

Base path: `/api/v2/products`

```http
GET    /                  # List products in current workspace
POST   /                  # Create product
GET    /{id}             # Get product details
PATCH  /{id}             # Update product
DELETE /{id}             # Delete product
```

Product Schema:

```json
{
    "id": "uuid",
    "name": "string",
    "description": "string",
    "identifiers": {
        "purl": "pkg:supplier/product@version",
        "cpe": "cpe:2.3:...",
        "custom_id": "string"
    },
    "metadata": {
        "vendor": {
            "name": "string",
            "website": "string",
            "contact": "string"
        },
        "tags": ["string"],
        "category": "string",
        "lifecycle_status": "string",
        "custom_fields": {}
    },
    "created_at": "timestamp",
    "updated_at": "timestamp"
}
```

### Projects

Base path: `/api/v2/products/{product_id}/projects`

```http
GET    /                  # List projects in product
POST   /                  # Create project
GET    /{id}             # Get project details
PATCH  /{id}             # Update project
DELETE /{id}             # Delete project
```

Project Schema:

```json
{
    "id": "uuid",
    "product_id": "uuid",
    "name": "string",
    "description": "string",
    "metadata": {
        "type": "string",          # application, library, service
        "status": "string",        # active, archived
        "tags": ["string"],
        "custom_fields": {}
    },
    "created_at": "timestamp",
    "updated_at": "timestamp"
}
```

### Components

Base path: `/api/v2/projects/{project_id}/components`

```http
GET    /                  # List components in project
POST   /                  # Create component
GET    /{id}             # Get component details
PATCH  /{id}             # Update component
DELETE /{id}             # Delete component
```

Component Schema:

```json
{
    "id": "uuid",
    "project_id": "uuid",
    "name": "string",
    "description": "string",
    "identifiers": {
        "purl": "pkg:supplier/component@version",
        "cpe": "cpe:2.3:...",
        "custom_id": "string"
    },
    "metadata": {
        "type": "string",          # library, framework, service, etc.
        "tags": ["string"],
        "lifecycle_status": "string",
        "custom_fields": {}
    },
    "created_at": "timestamp",
    "updated_at": "timestamp"
}
```

### Versions (Product-Component Mapping)

Base path: `/api/v2/products/{product_id}/versions`

```http
GET    /                  # List versions
POST   /                  # Create version
GET    /{version}        # Get version details
PATCH  /{version}        # Update version
DELETE /{version}        # Delete version

# Artifact Associations
GET    /{version}/artifacts                # List artifacts for version
POST   /{version}/artifacts/{artifact_id}  # Associate artifact with version
DELETE /{version}/artifacts/{artifact_id}  # Remove artifact from version
```

Version Schema:

```json
{
    "product_id": "uuid",
    "version": "string",          # Semantic version
    "release_date": "date",
    "status": "string",           # draft, published, archived
    "metadata": {
        "release_notes": "string",
        "release_type": "string", # major, minor, patch
        "distribution": {
            "channel": "string",  # stable, beta, etc.
            "platform": "string"  # linux/amd64, etc.
        },
        "custom_fields": {}
    },
    "artifacts": [
        {
            "id": "uuid",
            "type": "string",     # sbom, vex, etc.
            "format": "string",   # cyclonedx, spdx, etc.
            "component_id": "uuid" # Reference to source component
        }
    ],
    "created_at": "timestamp",
    "updated_at": "timestamp"
}
```

### Artifacts

Base path: `/api/v2/artifacts`

```http
GET    /                  # List artifacts
POST   /                  # Create artifact
GET    /{id}             # Get artifact details
PATCH  /{id}             # Update artifact
DELETE /{id}             # Delete artifact

# CycloneDX Support
POST   /cyclonedx/{spec_version}/metadata  # Enrich CycloneDX metadata
{
    "metadata": {},      # Original CycloneDX metadata
    "options": {
        "override_name": false,
        "override_metadata": false
    }
}

# SBOM Validation
POST   /validate
{
    "type": "sbom",
    "format": "cyclonedx",
    "spec_version": "1.5",
    "content": {}
}
```

Artifact Schema:

```json
{
    "id": "uuid",
    "component_id": "uuid",    # Reference to source component
    "type": "string",         # sbom, vex, certification, etc.
    "format": "string",       # cyclonedx, spdx, csaf, etc.
    "version": "string",      # Artifact version
    "content": {},           # Artifact-specific content
    "metadata": {
        "created_at": "timestamp",
        "created_by": "string",
        "source": "string",    # api, upload, ci, etc.
        "validation": {
            "status": "string",
            "errors": []
        },
        "custom_fields": {}
    }
}
```

## Search Capabilities

```http
# Product Search
GET /search/products
    ?q=search_term
    ?category=string
    ?tags=tag1,tag2
    ?lifecycle_status=active

# Project Search
GET /search/projects
    ?product_id=uuid
    ?type=application
    ?status=active
    ?q=search_term

# Component Search
GET /search/components
    ?product_id=uuid
    ?project_id=uuid
    ?type=library
    ?q=search_term

# Version Search
GET /search/versions
    ?product_id=uuid
    ?status=published
    ?channel=stable

# Artifact Search
GET /search/artifacts
    ?component_id=uuid
    ?type=sbom,vex
    ?format=cyclonedx
```

## Search and Discovery

### Product Search

```http
GET /api/v2/search/products
    ?q=search_term
    ?category=string
    ?tags=tag1,tag2
    ?lifecycle_status=active
```

### Release Search

```http
GET /api/v2/search/releases
    ?product_id=uuid
    ?version=1.0.0
    ?status=published
    ?channel=stable
```

### Artifact Search

```http
GET /api/v2/search/artifacts
    ?type=sbom,vex
    ?format=cyclonedx
    ?product_id=uuid
    ?release_version=1.0.0
    ?purl=pkg:...
```

Advanced Search:

```http
POST /api/v2/search/artifacts
{
    "query": {
        "type": ["sbom", "vex"],
        "format": "cyclonedx",
        "product": {
            "purl": "pkg:supplier/product",
            "version_range": ">=1.0.0 <2.0.0"
        },
        "content": {
            "vulnerabilities": {
                "severity": "high"
            }
        }
    },
    "include": ["metadata"],
    "sort": [
        {"field": "created_at", "order": "desc"}
    ]
}
```

## Batch Operations

### Bulk Artifact Upload

```http
POST /api/v2/artifacts/batch
{
    "artifacts": [
        {
            "type": "sbom",
            "format": "cyclonedx",
            "content": { ... }
        }
    ],
    "options": {
        "validate_only": false,
        "auto_associate": true,
        "product_id": "uuid",
        "release_version": "1.0.0"
    }
}
```

### Bulk Release Update

```http
PATCH /api/v2/products/{product_id}/releases/batch
{
    "versions": ["1.0.0", "1.1.0"],
    "updates": {
        "status": "archived"
    }
}
```

## Analytics and Statistics

Base path: `/api/v2/analytics`

```http
# Get workspace statistics
GET /stats
    ?product_id=uuid     # Optional: Filter by product
    ?project_id=uuid     # Optional: Filter by project
    ?component_id=uuid   # Optional: Filter by component

Response:
{
    "total_products": 10,
    "total_projects": 25,
    "total_components": 100,
    "license_distribution": {
        "MIT": 45,
        "Apache-2.0": 30,
        "GPL-3.0": 25
    },
    "recent_artifacts": [
        {
            "id": "uuid",
            "type": "sbom",
            "format": "cyclonedx",
            "created_at": "timestamp",
            "product": {
                "id": "uuid",
                "name": "string"
            }
        }
    ],
    "vulnerability_summary": {
        "critical": 5,
        "high": 10,
        "medium": 20,
        "low": 30
    }
}

# Get product statistics
GET /stats/products/{product_id}

# Get project statistics
GET /stats/projects/{project_id}

# Get component statistics
GET /stats/components/{component_id}
```

## Component Metadata Management

Base path: `/api/v2/components/{component_id}`

```http
# Get component metadata
GET /metadata
{
    "name": "string",
    "description": "string",
    "supplier": {
        "name": "string",
        "url": "string",
        "contact": "string"
    },
    "identifiers": {
        "purl": "pkg:supplier/component@version",
        "cpe": "cpe:2.3:...",
        "custom_id": "string"
    },
    "licenses": [
        {
            "id": "MIT",
            "url": "https://opensource.org/licenses/MIT"
        }
    ],
    "custom_fields": {}
}

# Update component metadata
PATCH /metadata
{
    "name": "string",
    "description": "string",
    // ... other fields
}
```

# Migration Guide

This document outlines the changes between API versions and provides guidance for migrating your applications.

## V1 to V2 Migration

### Breaking Changes

#### Teams to Workspaces Transition

The concept of "teams" has been replaced with "workspaces" to better reflect the organizational structure:

- All API endpoints that previously used `team_id` now use `workspace_id`
- The `/api/v1/teams` endpoint is replaced with `/api/v2/workspaces`
- Authentication tokens are now workspace-scoped instead of team-scoped
- Team-related environment variables should be updated to use the `WORKSPACE_` prefix

Example changes:

```diff
- GET /api/v1/teams/{team_id}/products
+ GET /api/v2/products?workspace_id={workspace_id}

- Authorization: Bearer team_<token>
+ Authorization: Bearer workspace_<token>

- TEAM_API_KEY=<key>
+ WORKSPACE_API_KEY=<key>
```

#### Resource Hierarchy Changes

The resource hierarchy has been restructured to better reflect the relationships between resources:

Old V1 structure:

```text
/api/v1/
    sboms/
        artifact/cyclonedx/{component_id}  # Upload CycloneDX SBOM
        artifact/spdx/{component_id}       # Upload SPDX SBOM
        component/{component_id}/meta      # Component metadata
        {item_type}/{item_id}/public_status  # Public status management
        user-items/{item_type}            # User-specific views
        stats                             # Statistics and analytics
```

New V2 structure:

```text
/api/v2/
    products/                  # Product management
        {id}/projects/         # Projects under product
        {id}/releases/         # Release management
    projects/                  # Project operations
        {id}/components/       # Components under project
    artifacts/                 # Artifact management
        cyclonedx/            # CycloneDX support
        validate/             # SBOM validation
    analytics/                # Statistics and insights
```

Key changes:

- Products are now the primary resource container
- Projects are directly linked to products
- Components are directly linked to projects
- Releases provide versioning and artifact management
- All resources are workspace-scoped through authentication
- Improved analytics and validation capabilities

#### Authentication Changes

- API keys are now workspace-scoped and follow a new format
- Session cookies now include workspace context
- Bearer tokens include workspace information in the payload

### New Features

- Rich metadata support for products and components
- Improved search capabilities across all resources
- Release-based artifact management
- Enhanced analytics and statistics
- Built-in SBOM validation
- CycloneDX version-specific support

### Deprecations

The following endpoints are deprecated and will be removed in V3:

- `/api/v1/sboms/*` - Use new artifact and release endpoints instead
- `/api/v1/rename/*` - Use PATCH endpoints on specific resources instead
- `/api/v1/users/teams/*` - Use workspace membership endpoints instead

### Migration Steps

1. Update API endpoint URLs to use the new V2 paths
2. Replace all instances of `team_id` with `workspace_id` in your code
3. Update authentication tokens to use workspace-scoped credentials
4. Update environment variables to use the `WORKSPACE_` prefix
5. Migrate data to follow the new resource hierarchy
6. Update API client libraries to the latest versions

### Migration Script

A migration script is available to help automate these changes:

```bash
# Coming soon
python manage.py migrate_to_v2 --workspace-id <id>
```

## Support

For assistance with migration:

1. Check the [API documentation](../api/api-design.md) for detailed endpoint specifications
2. Review the [common use cases](../api/use-cases.md) for examples
3. Contact support for migration assistance

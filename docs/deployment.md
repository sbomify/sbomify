# Deployment Process

This document outlines how sbomify is deployed to our hosting environments.

## Overview

The application is deployed to [fly.io](https://fly.io) using GitHub Actions. We have two environments:

1. **Staging** - Deployed automatically when changes are pushed to the `master` branch
2. **Production** - Deployed automatically when a new version tag (e.g., `v1.2.3`) is created

## GitHub Actions Workflow

The deployment process is integrated into the main CI/CD workflow (`.github/workflows/ci-cd.yml`), which:

1. Runs all tests and quality checks
2. Builds and tests Docker images
3. Deploys to the appropriate environment based on the trigger:
   - Master branch pushes → Staging
   - Version tags → Production
4. Generates an SBOM for tagged releases (after successful production deployment)

This integrated approach ensures that deployments only happen after all tests and checks have passed successfully.

## Configuration

The deployment uses the following GitHub Secrets:

- `FLY_CONFIG_STAGE` - The fly.toml configuration for the staging environment
- `FLY_CONFIG_PROD` - The fly.toml configuration for the production environment
- `FLY_TOKEN` - The API token for authenticating with fly.io

## Manual Deployment

If needed, you can manually trigger the CI/CD workflow from the GitHub Actions tab, which will run the full test suite and deploy if successful.

## Troubleshooting

If a deployment fails:

1. Check the GitHub Actions logs for error messages
2. Verify that the fly.io configuration is correct
3. Ensure the FLY_TOKEN has the necessary permissions
4. Check the application logs on fly.io using `flyctl logs`

## Rollback Procedure

To rollback to a previous version:

1. For production: Create a new tag pointing to the previous working commit
2. For staging: Push a revert commit to the master branch
3. Alternatively, use the fly.io dashboard to rollback to a previous deployment

## Fly.io Configuration

### Initial Setup

First, create the application and set up Sentry:

```bash
flyctl app create sbomify-backend-stage  # For staging
flyctl app create sbomify-backend        # For production
flyctl ext sentry create
```

### DNS Configuration

Point your DNS record to `[app CNAME].fly.dev`, then add SSL certificate:

```bash
fly certs add <domain>
```

### Database Setup

Create and attach a Postgres database:

```bash
fly postgres create
fly postgres attach [database name] -a [app name]
```

### Authentication Configuration

Authentication methods differ by environment:

### Local Development
Authentication for local development is handled through Django's admin interface. See the [README.md](../README.md#local-development) for setup instructions.

### Production Environment
> **Note**: Production authentication is in transition. See [issue #1](https://github.com/sbomify/sbomify/issues/1) for details.

#### Current: Auth0 Setup (Production Only)
Create a "Regular Web Application" with the following settings:

| Setting | Value |
|---------|-------|
| APPLICATION LOGIN URI | https://[yourdomain] |
| ALLOWED CALLBACK URLs | https://[yourdomain]/complete/auth0 |
| ALLOWED LOGOUT URLs | https://[yourdomain] |
| ALLOWED WEB ORIGINS | https://[yourdomain] |

### Application Configuration

Set up the required environment variables:

```bash
# Base configuration
fly secrets set APP_BASE_URL=https://[your domain]
fly secrets set SECRET_KEY=[...]  # Generate this safely offline

# Auth0 configuration
fly secrets set SOCIAL_AUTH_AUTH0_DOMAIN=[...]
fly secrets set SOCIAL_AUTH_AUTH0_KEY=[...]
fly secrets set SOCIAL_AUTH_AUTH0_SECRET=[...]

# Monitoring and email
fly secrets set SENTRY_DSN=[...]
fly secrets set DEFAULT_FROM_EMAIL=noreply@sbomify.com
fly secrets set SENDGRID_API_KEY=[...]
```

### Storage Configuration

We need two S3-compatible buckets (create these manually in Tigris):

- `sbomify-[env]-media` (public access required)
- `sbomify-[env]-sboms`

Attach the media bucket to the application:

```bash
fly storage update sbomify-[env]-media -a [app name]
```

Configure storage environment variables:

```bash
# Bucket configuration
flyctl secrets set AWS_MEDIA_STORAGE_BUCKET_NAME=sbomify-[env]-media
flyctl secrets set AWS_MEDIA_STORAGE_BUCKET_URL=${AWS_ENDPOINT_URL_S3}/${AWS_MEDIA_STORAGE_BUCKET_NAME}
flyctl secrets set AWS_SBOMS_STORAGE_BUCKET_NAME=sbomify-[env]-sboms
flyctl secrets set AWS_SBOMS_STORAGE_BUCKET_URL=${AWS_ENDPOINT_URL_S3}/${AWS_SBOMS_STORAGE_BUCKET_NAME}

# Access credentials (get these from Tigris)
flyctl secrets set AWS_MEDIA_ACCESS_KEY_ID=[redacted]
flyctl secrets set AWS_MEDIA_SECRET_ACCESS_KEY=[redacted]
flyctl secrets set AWS_SBOMS_ACCESS_KEY_ID=[redacted]
flyctl secrets set AWS_SBOMS_SECRET_ACCESS_KEY=[redacted]
```

## Deployment Rules

### Staging

- Deploys automatically when new commits are pushed to master
- Uses the configuration from `FLY_CONFIG_STAGE` secret

### Production

- Only deploys on version tags (e.g., v1.0.0)
- Requires successful tests and Docker builds
- Uses the configuration from `FLY_CONFIG_PROD` secret

# Deployment Process

> **⚠️ NOTE: This documentation is a work in progress and may change. Please consult the team for the latest deployment procedures.**

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

Authentication for all environments is now handled via Keycloak, which is managed as part of the Docker Compose environment.

#### Keycloak Setup

Keycloak is started automatically with Docker Compose. You do not need to run Keycloak manually.

To start Keycloak (and all other services) in development, simply run:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Keycloak will be available at <http://keycloak:8080/>.

> **Note:** For the development environment to work, you must have the following entry in your `/etc/hosts` file:

```bash
127.0.0.1   keycloak
```

Persistent storage for Keycloak is managed by Docker using a named volume (`keycloak_data`).

##### 1. Create a Realm

1. Hover over the dropdown in the top-left corner (showing "master") and click "Create Realm"
2. Enter "sbomify" as the realm name
3. Click "Create"

##### 2. Create a Client

1. Navigate to "Clients" in the left sidebar
2. Click "Create client"
3. Enter the following details:
   - Client type: OpenID Connect
   - Client ID: sbomify
4. Click "Next"
5. Enable "Client authentication"
6. Enable "Standard flow" and "Direct access grants"
7. Click "Next"
8. Add valid redirect URIs (adjust according to your deployment environment):
   - <https://sbomify.example.com/>*
9. Add valid web origins:
   - <https://sbomify.example.com>
10. Click "Save"

The realm account console is at: <https://auth.example.com/realms/sbomify/account>

##### 3. Get Client Secret

1. Navigate to the "Credentials" tab of your new client
2. Copy the client secret (you will need this for your Django settings)

##### 4. Configure Django for Keycloak

Set these environment variables in your `.env` file or in your Docker Compose configuration:

```env
USE_KEYCLOAK=True
KEYCLOAK_SERVER_URL=https://auth.example.com/
KEYCLOAK_REALM=sbomify
KEYCLOAK_CLIENT_ID=sbomify
KEYCLOAK_CLIENT_SECRET=your-client-secret-from-previous-step
KEYCLOAK_ADMIN_USERNAME=admin
KEYCLOAK_ADMIN_PASSWORD=admin
```

> **Note:** If you set these in `.env`, make sure your docker-compose file includes an `env_file: .env` line for the relevant service, or that your environment is loaded accordingly. If you set them in the compose file, they will override `.env` values for that service.

##### 5. Migrating Existing Users

Django comes with a management command to migrate existing users from Django to Keycloak:

```bash
# Dry run (does not create users in Keycloak, just shows what would happen)
python manage.py migrate_to_keycloak --dry-run

# Migrate all users
python manage.py migrate_to_keycloak

# Migrate all users and send password reset emails
python manage.py migrate_to_keycloak --send-reset-emails

# Migrate a specific user
python manage.py migrate_to_keycloak --user-email user@example.com
```

During migration:

1. Users are created in Keycloak with the same email, username, first name, and last name as in Django
2. A random temporary password is set for each user
3. Optionally, password reset emails can be sent to users

##### 6. Testing the Integration

To test the integration:

1. Make sure Keycloak is running
2. Set `USE_KEYCLOAK=True` in your `.env` file
3. Start the Django server
4. Navigate to the login page
5. Click "Log In / Register"
6. You should be redirected to the Keycloak login page
7. After signing in, you should be redirected back to the Django application

##### 7. Troubleshooting

###### Keycloak Integration Issues

- Check that Keycloak is running and accessible at <http://keycloak:8080/>
- Verify your realm name and client ID are correct
- Ensure your client secret is correctly copied to your `.env` file
- Confirm that redirect URIs in Keycloak match your Django application URLs

###### User Migration Issues

- Check the logs for detailed error messages
- Verify that Keycloak admin credentials are correct
- Ensure that users have valid email addresses in the Django database

###### Login Issues

- Clear your browser cookies and try again
- Check that the Keycloak server is running and accessible
- Verify that the user exists in Keycloak (check the Users section in the Keycloak admin console)

##### Keycloak Bootstrapping

Keycloak is automatically bootstrapped using the script at `bin/keycloak-bootstrap.sh` when you start the development environment with Docker Compose. This script uses environment variables (such as `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_ADMIN_USERNAME`, `KEYCLOAK_ADMIN_PASSWORD`, `KEYCLOAK_CLIENT_SECRET`, etc.) to configure the realm, client, and credentials. **You do not need to edit the script itself**—just set the appropriate environment variables in your `.env` file or Docker Compose configuration to control the bootstrap process.

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

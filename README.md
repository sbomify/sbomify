# sbomify

sbomify is a Software Bill of Materials (SBOM) management platform that can be self-hosted or accessed through [app.sbomify.com](https://app.sbomify.com). The platform provides a centralized location to upload and manage your SBOMs, allowing you to share them with stakeholders or make them publicly accessible.

The sbomify backend integrates with our [github actions module](https://github.com/sbomify/github-action) to automatically generate SBOMs from lock files and docker files.

For more information, see [sbomify.com](https://sbomify.com).

## Roadmap and Goals

- Be compatible with both CycloneDX and SPDX SBOM formats
- Be compatible with Project Koala / [Transparency Exchange API (TEA)](https://github.com/CycloneDX/transparency-exchange-api/)

## Releases

For information about cutting new releases, see [RELEASE.md](docs/RELEASE.md).

## Deployment

The application is automatically deployed to [fly.io](https://fly.io) when changes are pushed to the `master` branch (staging) or when a new version tag is created (production).

For detailed information about the deployment process, including:

- CI/CD workflow
- Fly.io configuration
- Environment setup
- Storage configuration

See [docs/deployment.md](docs/deployment.md).

## Local Development

### Authentication During Development

For local development, authentication is handled through Django's admin interface:

```bash
# Create a superuser for local development
docker compose \
    -f docker-compose.yml \
    -f docker-compose.dev.yml exec \
    sbomify-backend \
    poetry run python manage.py createsuperuser
```

Then access the admin interface at `http://localhost:8000/admin` to log in.

> **Note**: Production environments use different authentication methods. See [docs/deployment.md](docs/deployment.md) for production authentication setup.

### Development Prerequisites

- Python 3.12+
- Poetry
- Docker (for running PostgreSQL and Minio)
- Bun (for JavaScript development)

### API Documentation

The API documentation is available at:

- Interactive API docs (Swagger UI): `http://localhost:8000/api/v1/docs`
- OpenAPI specification: `http://localhost:8000/api/v1/openapi.json`

These endpoints are available when running the development server.

### Setup

Copy `.env.example` to `.env` and adjust values as needed:

```bash
cp .env.example .env
```

Start the development environment (recommended method):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml build
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Create a local admin account:

```bash
docker compose \
    -f docker-compose.yml \
    -f docker-compose.dev.yml exec \
    -e DJANGO_SUPERUSER_USERNAME=sbomifyadmin \
    -e DJANGO_SUPERUSER_PASSWORD=sbomifyadmin \
    -e DJANGO_SUPERUSER_EMAIL=admin@sbomify.com \
    sbomify-backend \
    poetry run python manage.py createsuperuser --noinput
```

Access the application:

- Admin interface: `http://localhost:8000/admin`
- Main application: `http://localhost:8000`

> **Note**: For production deployment information, see [docs/deployment.md](docs/deployment.md).

#### Alternative: Running Locally (without Docker for Django)

- Start required services in Docker:

```bash
# Start both PostgreSQL and MinIO
docker compose up sbomify-db sbomify-minio sbomify-createbuckets -d
```

- Install dependencies:

```bash
poetry install
bun install  # for JavaScript dependencies
```

- Run migrations:

```bash
poetry run python manage.py migrate
```

- Start the development servers:

```bash
# In one terminal, start Django
poetry run python manage.py runserver

# In another terminal, start Vite
bun run dev
```

### Configuration

#### Development Server Settings

The application uses Vite for JavaScript development. The following environment
variables control the development servers:

```bash
# Vite development settings
DJANGO_VITE_DEV_MODE=True
DJANGO_VITE_DEV_SERVER_PORT=5170
DJANGO_VITE_DEV_SERVER_HOST=http://localhost

# Static and development server settings
STATIC_URL=/static/
DEV_JS_SERVER=http://127.0.0.1:5170
WEBSITE_BASE_URL=http://127.0.0.1:8000
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
VITE_WEBSITE_BASE_URL=http://127.0.0.1:8000
```

These settings are preconfigured in the `.env.example` file.

#### Keycloak Authentication Setup

Keycloak is now managed as part of the Docker Compose environment. You do not need to run Keycloak manually.

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
8. Add valid redirect URIs (adjust according to your environment):
   - <http://localhost:8000/>*
   - <http://127.0.0.1:8000/>*
9. Add valid web origins:
   - <http://localhost:8000>
   - <http://127.0.0.1:8000>
10. Click "Save"

The realm account console is at: <http://keycloak:8080/realms/sbomify-dev/account>

##### 3. Get Client Secret

1. Navigate to the "Credentials" tab of your new client
2. Copy the client secret (you will need this for your Django settings)

##### 4. Configure Django for Keycloak

You can set these environment variables either in your `.env` file (recommended for local development), or directly in your `docker-compose.dev.yml` (or `docker-compose.yml`) under the `environment` section for the relevant services:

```env
USE_KEYCLOAK=True
KEYCLOAK_SERVER_URL=http://keycloak:8080/
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
5. Click "Sign in with Keycloak"
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

#### S3/Minio Storage

The application uses S3-compatible storage for storing files and assets. In
development, we use Minio as a local S3 replacement.

- When running with Docker Compose, everything is configured automatically
- When running locally (Django outside Docker):
  - Make sure Minio is running via Docker:
    `docker compose up sbomify-minio sbomify-createbuckets -d`
  - Set `AWS_S3_ENDPOINT_URL=http://localhost:9000` in your `.env`
  - The required buckets (`sbomify-media` and `sbomify-sboms`) will be created
    automatically

You can access the Minio console at:

- `http://localhost:9001`
- Default credentials: minioadmin/minioadmin

### Running test cases

```bash
poetry run coverage run -m pytest --pdb -x -s
poetry run coverage report
```

### JS build tooling

For frontend JS work, setting up JS tooling is required.

#### Bun

```bash
curl -fsSL https://bun.sh/install | bash
```

In the project folder at the same level as `package.json`:

```bash
bun install
```

#### Linting

For JavaScript/TypeScript linting:

```bash
# Check for linting issues (used in CI and can be run locally)
bun lint

# Fix linting issues automatically (local development only)
bun lint-fix
```

#### Run vite dev server

```bash
bun run dev
```

## Production Deployment

### Production Prerequisites

- Docker and Docker Compose
- S3-compatible storage (like Amazon S3 or Google Cloud Storage)
- PostgreSQL database
- Reverse proxy (e.g., Nginx) for production deployments

### Docker Compose Configuration

A `docker-compose.prod.yml` file is available for production-like setups. **Note:** This configuration is not fully tested and is not recommended for use in real production environments as-is. The provided settings are for demonstration and staging purposes only and will be updated and improved in the future.

To try a production-like stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

You will need to set appropriate environment variables (see `.env.example` for guidance) and ensure your reverse proxy, storage, and database are configured securely.

> **Warning:** Do not use the provided production compose setup as-is for real deployments. Review and harden all settings, secrets, and network exposure before using in production.

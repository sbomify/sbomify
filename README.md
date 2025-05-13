[![CI/CD Pipeline](https://github.com/sbomify/sbomify/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/sbomify/sbomify/actions/workflows/ci-cd.yml)

![sbomify logo](static/img/sbomify.svg)

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

For full production deployment instructions, see [the deployment guide](docs/deployment.md).

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
- Poetry (Python package manager)
- Docker (for running PostgreSQL and Minio)
- Bun (for JavaScript development)

#### Installing Poetry

- Install Poetry using the official installer:

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

- Verify the installation:

```bash
poetry --version
```

- Configure Poetry to create virtual environments in the project directory:

```bash
poetry config virtualenvs.in-project true
```

#### Installing Dependencies

- Install Python dependencies using Poetry:

```bash
# Install all dependencies including development dependencies
poetry install

# Activate the virtual environment
poetry shell
```

- Install JavaScript dependencies using Bun:

```bash
bun install
```

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
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.yml build
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.yml up
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

**Note:** For the development environment to work, you must have the following entry in your `/etc/hosts` file:

```bash
127.0.0.1   keycloak
```

Persistent storage for Keycloak is managed by Docker using a named volume (`keycloak_data`).

##### Keycloak Bootstrapping

Keycloak is automatically bootstrapped using the script at `bin/keycloak-bootstrap.sh` when you start the development environment with Docker Compose. This script uses environment variables (such as `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_ADMIN_USERNAME`, `KEYCLOAK_ADMIN_PASSWORD`, `KEYCLOAK_CLIENT_SECRET`, etc.) to configure the realm, client, and credentials. **You do not need to edit the script itself**—just set the appropriate environment variables in your `.env` file or Docker Compose configuration to control the bootstrap process.

To start Keycloak (and all other services) in development, simply run:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Keycloak will be available at <http://keycloak:8080/>.

```bash
127.0.0.1   keycloak
```

Persistent storage for Keycloak is managed by Docker using a named volume (`keycloak_data`).

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

First, ensure you have the test environment set up:

```bash
# Copy the test environment file
cp test_env .env.test
```

Then run the tests:

```bash
# Run all tests with coverage
poetry run coverage run -m pytest

# Run specific test groups
poetry run coverage run -m pytest core/tests/
poetry run coverage run -m pytest sboms/tests/
poetry run coverage run -m pytest teams/tests/

# Run with debugger on failure
poetry run coverage run -m pytest --pdb -x -s

# Generate coverage report
poetry run coverage report
```

The test environment uses SQLite in-memory database for faster test execution. Test coverage must be at least 80% to pass CI checks.

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

### Pre-commit Checks

The project uses pre-commit hooks to ensure code quality and consistency. The hooks check for:

- Code formatting (ruff-format)
- Python linting (ruff)
- Security issues (bandit)
- Markdown formatting
- TypeScript type checking
- JavaScript/TypeScript linting
- Merge conflicts
- Debug statements

To set up pre-commit:

- Install pre-commit hooks:

```bash
poetry run pre-commit install
```

- Run pre-commit checks manually:

```bash
# Check all files
poetry run pre-commit run --all-files

# Check staged files only
poetry run pre-commit run
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

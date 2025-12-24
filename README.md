[![CI/CD Pipeline](https://github.com/sbomify/sbomify/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/sbomify/sbomify/actions/workflows/ci-cd.yml)

![sbomify logo](sbomify/static/img/sbomify.svg)

[![sbomified](https://sbomify.com/assets/images/logo/badge.svg)](https://app.sbomify.com/public/product/eP_4dk8ixV/)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/sbomify/sbomify/badge)](https://securityscorecards.dev/viewer/?uri=github.com/sbomify/sbomify&sort_by=check-score&sort_direction=desc)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/10952/badge)](https://www.bestpractices.dev/projects/10952)

sbomify is a Software Bill of Materials (SBOM) and document management platform that can be self-hosted or accessed through [app.sbomify.com](https://app.sbomify.com). The platform provides a centralized location to upload and manage your SBOMs and related documentation, allowing you to share them with stakeholders or make them publicly accessible.

The sbomify backend integrates with our [github actions module](https://github.com/sbomify/github-action) to automatically generate SBOMs from lock files and docker files.

For more information, see [sbomify.com](https://sbomify.com).

## Features

### SBOM Management

- Support for both CycloneDX and SPDX SBOM formats
- Upload SBOMs via web interface or API
- Vulnerability scanning integration
- Public and private access controls
- Workspace-based organization

### Document Management

- Upload and manage document artifacts (specifications, manuals, reports, compliance documents, etc.)
- Associate documents with software components
- Version control for documents
- Secure storage with configurable S3 buckets
- Public and private document sharing

### Organization

- **Components**: Core entities that can contain either SBOMs or documents
- **Projects**: Group related components together
- **Products**: Organize multiple projects
- **Workspaces**: Control access and permissions

## Roadmap and Goals

- Be compatible with both CycloneDX and SPDX SBOM formats
- Be compatible with Project Koala / [Transparency Exchange API (TEA)](https://github.com/CycloneDX/transparency-exchange-api/)

## Releases

For information about cutting new releases, see [RELEASE.md](docs/RELEASE.md).

## Architecture Decision Records (ADRs)

We use Architecture Decision Records (ADRs) to document significant architectural decisions made in this project. ADRs provide context and rationale for decisions, helping current and future contributors understand why certain approaches were chosen.

For all ADRs, see the [docs/ADR](docs/ADR) folder.

## Deployment

For detailed information about the deployment process, including:

- CI/CD workflow
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
    uv run python manage.py createsuperuser
```

Then access the admin interface at `http://localhost:8000/admin` to log in.

> **Note**: Production environments use different authentication methods. See [docs/deployment.md](docs/deployment.md) for production authentication setup.

### Development Prerequisites

- Python 3.12+
- uv (Python package manager)
- Docker (for running PostgreSQL and Minio)
- Bun (for JavaScript development)

#### Installing uv

- Install uv using the official installer:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

- Verify the installation:

```bash
uv --version
```

#### Installing Dependencies

- Install Python dependencies using uv:

```bash
# Install all dependencies including development dependencies
uv sync

# Run commands using uv
uv run python manage.py --help
```

- Install JavaScript dependencies using Bun:

```bash
bun install
```

### API Documentation

The API documentation is available at:

- Interactive API docs (Swagger UI): `http://localhost:8000/api/v1/docs`
- OpenAPI specification: `http://localhost:8000/api/v1/openapi.json`

The API provides endpoints for managing:

- **SBOMs**: Upload, retrieve, and manage Software Bill of Materials
- **Documents**: Upload, retrieve, and manage document artifacts
- **Components**: Manage components that contain SBOMs or documents
- **Projects & Products**: Organize and group components
- **Workspaces**: User management and access control

These endpoints are available when running the development server.

### Setup

Configure environment variables by setting them in your shell or using Docker Compose override files.

**Important: Add to `/etc/hosts`**

For the development environment to work properly with Keycloak authentication, you must add the following entry to your `/etc/hosts` file:

```bash
127.0.0.1   keycloak
```

Start the development environment (recommended method):

```bash
./bin/developer_mode.sh build
./bin/developer_mode.sh up
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
    uv run python manage.py createsuperuser --noinput
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
uv sync
bun install  # for JavaScript dependencies
```

- Run migrations:

```bash
uv run python manage.py migrate
```

- Start the development servers:

```bash
# In one terminal, start Django
uv run python manage.py runserver

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

These settings can be configured using environment variables.

#### Keycloak Authentication Setup

Keycloak is now managed as part of the Docker Compose environment. You do not need to run Keycloak manually.

Persistent storage for Keycloak is managed by Docker using a named volume (`keycloak_data`).

##### Keycloak Bootstrapping

Keycloak is automatically bootstrapped using the script at `bin/keycloak-bootstrap.sh` when you start the development environment with Docker Compose. This script uses environment variables (such as `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_ADMIN_USERNAME`, `KEYCLOAK_ADMIN_PASSWORD`, `KEYCLOAK_CLIENT_SECRET`, etc.) to configure the realm, client, and credentials. **You do not need to edit the script itself**—just set the appropriate environment variables in your Docker Compose configuration to control the bootstrap process.

When running in development mode (using `docker-compose.dev.yml`), the bootstrap script automatically:

- **Disables SSL requirements** for easier local development
- **Creates test users** for authentication testing:
  - **John Doe** - Username: `jdoe`, Password: `foobar123`, Email: `jdoe@example.com`
  - **Steve Smith** - Username: `ssmith`, Password: `foobar123`, Email: `ssmith@example.com`

These development-specific configurations are controlled by the `KEYCLOAK_DEV_MODE` environment variable and are only applied when running the development Docker Compose stack.

To start Keycloak (and all other services) in development, simply run:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Keycloak will be available at <http://keycloak:8080/>.

#### S3/Minio Storage

The application uses S3-compatible storage for storing files and assets. In
development, we use Minio as a local S3 replacement.

- When running with Docker Compose, everything is configured automatically
- When running locally (Django outside Docker):
  - Make sure Minio is running via Docker:
    `docker compose up sbomify-minio sbomify-createbuckets -d`
  - Set `AWS_ENDPOINT_URL_S3=http://localhost:9000` in your environment variables
  - The required buckets (`sbomify-media`, `sbomify-sboms`, and optionally `sbomify-documents`) will be created
    automatically

##### Storage Buckets

The application uses separate S3 buckets for different types of content:

- **Media Bucket**: User avatars, workspace logos, and other media assets
- **SBOMs Bucket**: Software Bill of Materials files
- **Documents Bucket**: Document artifacts (specifications, manuals, reports, compliance documents, etc.)
  - If not configured separately, documents will use the SBOMs bucket automatically
  - For production, it's recommended to use a separate bucket for better organization and access control

You can access the Minio console at:

- `http://localhost:9001`
- Default credentials: minioadmin/minioadmin

##### Production Storage Configuration

For production deployments, you can configure separate S3 buckets for documents:

```bash
# Optional: Configure dedicated documents bucket (recommended for production)
export AWS_DOCUMENTS_ACCESS_KEY_ID="your-documents-access-key"
export AWS_DOCUMENTS_SECRET_ACCESS_KEY="your-documents-secret-key"
export AWS_DOCUMENTS_STORAGE_BUCKET_NAME="your-documents-bucket"
export AWS_DOCUMENTS_STORAGE_BUCKET_URL="https://your-documents-bucket.s3.region.amazonaws.com"

# If not configured, documents will automatically use the SBOMs bucket
export AWS_SBOMS_ACCESS_KEY_ID="your-sboms-access-key"
export AWS_SBOMS_SECRET_ACCESS_KEY="your-sboms-secret-key"
export AWS_SBOMS_STORAGE_BUCKET_NAME="your-sboms-bucket"
export AWS_SBOMS_STORAGE_BUCKET_URL="https://your-sboms-bucket.s3.region.amazonaws.com"
```

Benefits of separate buckets:

- **Security**: Different access policies for SBOMs vs documents
- **Organization**: Clear separation of content types
- **Backup**: Independent backup strategies for different data types

#### Dependency Track Integration

sbomify supports integration with [Dependency Track](https://dependencytrack.org/) for advanced vulnerability management and analysis. Dependency Track integration is available for Business and Enterprise plans.

**Note:** Dependency Track only supports CycloneDX format SBOMs. SPDX SBOMs will automatically use OSV scanning regardless of workspace configuration.

##### Environment-Based Project Naming

When using a shared Dependency Track instance across multiple environments (development, staging, production), sbomify automatically prefixes project names with the environment to help differentiate them:

**Examples:**

- **Production** (`https://app.sbomify.com`): `prod-sbomify-{component-id}`
- **Staging** (`https://staging.sbomify.com`): `staging-sbomify-{component-id}`
- **Development** (`https://dev.sbomify.com`): `dev-sbomify-{component-id}`
- **Local** (`http://localhost:8000`): `local-sbomify-{component-id}`

**Custom Environment Prefix:**
You can override the automatic detection by setting the `DT_ENVIRONMENT_PREFIX` environment variable:

```bash
export DT_ENVIRONMENT_PREFIX="my-custom-env"
# Results in: my-custom-env-sbomify-{component-id}
```

This makes it easy to identify which environment a project belongs to when viewing your Dependency Track dashboard.

##### Required Permissions

To integrate with Dependency Track, you need to create an API token with the following permissions:

- `BOM_UPLOAD`
- `PROJECT_CREATION_UPLOAD`
- `VIEW_PORTFOLIO`
- `VIEW_VULNERABILITY`

You can create a token under **Administration → Access Management** in your Dependency Track instance (use the workspace management interface there).

##### DT Configuration

1. **Add Dependency Track Server** via Django admin:
   - Navigate to `/admin/vulnerability_scanning/dependencytrackserver/`
   - Click "Add Dependency Track Server"
   - Fill in the server details:
     - **Name**: Friendly name for the server
     - **URL**: Base URL of your Dependency Track instance
     - **API Key**: Token with required permissions
     - **Priority**: Lower numbers = higher priority for load balancing
     - **Max Concurrent Scans**: Maximum number of simultaneous SBOM uploads

2. **Configure Workspace Settings**:
   - Business/Enterprise workspaces can choose Dependency Track in **Settings → Integrations**
   - Enterprise workspaces can optionally configure custom Dependency Track instances
   - Business workspaces use the shared server pool

##### DT Features

- **Automatic Vulnerability Scanning**:
  - Community workspaces: Weekly vulnerability scans using OSV
  - Business/Enterprise workspaces: Vulnerability updates every 12 hours using Dependency Track
- **Load Balancing**: Distribute scans across multiple Dependency Track servers
- **Health Monitoring**: Automatic server health checks and capacity management
- **Historical Tracking**: Complete scan result history for trend analysis
- **Unified Results**: Consistent vulnerability data format across OSV and Dependency Track

### Running test cases

Before running tests, you need to up docker-compose.tests.yml:

```bash
docker compose -f docker-compose.tests.yml up -d
```

Run the tests using Django's test profile:

```bash
# Run all tests with coverage
uv run coverage run -m pytest

# Run specific test groups
uv run coverage run -m pytest core/tests/
uv run coverage run -m pytest sboms/tests/
uv run coverage run -m pytest teams/tests/

# Run with debugger on failure
uv run coverage run -m pytest --pdb -x -s

# Generate coverage report
uv run coverage report
```

Test coverage must be at least 80% to pass CI checks.

### E2E Snapshot (Screenshot) Tests

The project includes end-to-end snapshot tests that capture screenshots of the UI and compare them against baseline images. This helps ensure visual consistency across different screen sizes and after code changes.

#### Prerequisites for E2E Tests

Before running e2e snapshot tests, you need to:

**Build JavaScript assets:**

```bash
bun run build
```

This ensures that all static assets (JavaScript, CSS) are up-to-date before taking screenshots.

#### Writing Snapshot Tests

Here's an abstract example of how to write a snapshot test:

```python
@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestYourPageSnapshot:
    def test_your_page_snapshot(
        self,
        authenticated_page,
        your_test_fixtures,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        # Navigate to the page you want to test
        authenticated_page.goto("/your-page")
        authenticated_page.wait_for_load_state("networkidle")

        # Get or create baseline screenshot (stored in __snapshots__)
        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        
        # Take current screenshot
        current = snapshot.take_screenshot(authenticated_page, width=width)

        # Compare screenshots
        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
```

**Key components:**
 
- Use `@pytest.mark.django_db` to enable database access
- Use `@pytest.mark.parametrize("width", [...])` to test multiple screen sizes
- Inject the `authenticated_page` fixture for browser automation
- Inject the `snapshot` fixture for screenshot management
- Use `get_or_create_baseline_screenshot()` to get the baseline (creates it if missing)
- Use `take_screenshot()` to capture the current state
- Use `assert_screenshot()` to compare them

#### Running E2E Snapshot Tests

After building assets, you can use the dedicated E2E docker-compose stack to run snapshot tests:

```bash
# Start the test stack (database, chromium, and tests container)
docker compose -f docker-compose.tests.yml up -d

# Run all E2E snapshot tests inside the tests container
docker compose -f docker-compose.tests.yml exec tests uv run pytest sbomify/apps/<APP>/tests/e2e/

# Run a single E2E snapshot test (example)
docker compose -f docker-compose.tests.yml exec tests uv run pytest \
  sbomify/apps/<APP>/tests/e2e/test_your_page.py::TestYourPageSnapshot::test_your_page_snapshot[1920]
```

#### Working with Snapshot Tests

**New Tests**
When you write a new snapshot test, it will automatically create baseline screenshots in the `__snapshots__` directory (located at `sbomify/apps/<APP_NAME>/tests/e2e/__snapshots__/`). Simply run the test and verify that the generated screenshots look correct.

**Existing Tests - Passing**
If the test already exists and passes, everything is working as expected. No action needed.

**Existing Tests - Failing**
If a test fails, check the `__diffs__` directory (located at `sbomify/apps/<APP_NAME>/tests/e2e/__diffs__/`) to see what changed. The diff images show the differences between the baseline and current screenshots.

**Updating Outdated Snapshots**
If the diff screenshot in `__diffs__` shows that the new visual state is correct (i.e., the baseline snapshot is outdated), you need to update the baseline:

1. Delete the outdated snapshot file from `__snapshots__`
2. Re-run the test - it will automatically recreate the baseline screenshot with the current state

**Example:**

```bash
# Delete outdated snapshot
rm sbomify/apps/<APP_NAME>/tests/e2e/__snapshots__/test_your_page_snapshot[1920].jpg

# Re-run the test to create new baseline
uv run pytest sbomify/apps/<APP_NAME>/tests/e2e/test_your_page.py::TestYourPageSnapshot::test_your_page_snapshot
```

For a real-world example, see `sbomify/apps/core/tests/e2e/test_dashboard.py`.

### Test Data Management

The application includes management commands to help set up and manage test data in your development environment:

```bash
# Create a test environment with sample SBOM data
# If no workspace is specified, the first workspace in the database is used
# (the management command retains the legacy --team-id flag name for compatibility)
python manage.py create_test_sbom_environment

# Create test environment for a specific workspace (still uses the legacy --team-id flag)
python manage.py create_test_sbom_environment --team-id=your_team_id

# Clean up existing test data and create fresh environment
python manage.py create_test_sbom_environment --clean

# Clean up all test data across all workspaces
python manage.py cleanup_test_sbom_environment

# Clean up test data for a specific workspace (still uses the legacy --team-id flag)
python manage.py cleanup_test_sbom_environment --team-id=your_team_id

# Preview what would be deleted (dry run)
python manage.py cleanup_test_sbom_environment --dry-run
```

These commands will:

1. Create test products, projects, and components
2. Load real SBOM data from test files (both SPDX and CycloneDX formats)
3. Set up proper relationships between all entities
4. Allow you to clean up test data when needed

The test data is grouped by source (e.g., hello-world and sbomify) rather than by format, so each component will have both SPDX and CycloneDX SBOMs attached to it.

Note: You must have at least one workspace in the database to use these commands without specifying the legacy `--team-id` flag.

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
uv run pre-commit install
```

- Run pre-commit checks manually:

```bash
# Check all files
uv run pre-commit run --all-files

# Check staged files only
uv run pre-commit run
```

## Production Deployment

### Production Prerequisites

- Docker and Docker Compose
- S3-compatible storage (like Amazon S3 or Google Cloud Storage)
- PostgreSQL database
- Reverse proxy (e.g., Nginx) for production deployments

### Docker Compose Configuration

A `docker-compose.prod.yml` file is available for production-like setups. **Note:** This configuration is not fully tested and is not recommended for use in real production environments as-is. The provided settings are for demonstration and staging purposes only and will be updated and improved in the future.

For production deployments, generate a secure signing salt for signed URLs:

```bash
# Generate a secure signing salt for signed URLs
export SIGNED_URL_SALT="$(openssl rand -hex 32)"
```

The `SIGNED_URL_SALT` is used to sign download URLs for private components in product/project SBOMs.

To try a production-like stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

You will need to set appropriate environment variables and ensure your reverse proxy, storage, and database are configured securely.

> **Warning:** Do not use the provided production compose setup as-is for real deployments. Review and harden all settings, secrets, and network exposure before using in production.

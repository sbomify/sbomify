# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

sbomify is a Software Bill of Materials (SBOM) and document management platform. It supports both CycloneDX and SPDX formats, vulnerability scanning, compliance assessments, and document artifact management.

**Key principle**: sbomify never modifies security artifacts. Artifacts are stored exactly as received—immutable. All analysis (vulnerability scanning, compliance checking) produces separate output without altering the original artifact.

## Build and Development Commands

### Setup and Running

```bash
# Start development environment with Docker (recommended)
./bin/developer_mode.sh build
./bin/developer_mode.sh up

# Alternative: Run Django locally with Docker services
docker compose up sbomify-db sbomify-minio sbomify-createbuckets -d
uv sync && bun install
uv run python manage.py migrate
uv run python manage.py runserver  # Terminal 1
bun run dev                         # Terminal 2 (Vite)
```

### Testing

```bash
# Start test services first
docker compose -f docker-compose.tests.yml up -d

# Run all tests with coverage
uv run coverage run -m pytest

# Run specific test file or directory
uv run coverage run -m pytest sbomify/apps/sboms/tests/
uv run coverage run -m pytest sbomify/apps/core/tests/test_apis.py

# Run single test with debugger
uv run coverage run -m pytest --pdb -x -s sbomify/apps/sboms/tests/test_upload.py::test_name

# Generate coverage report (must be >= 80%)
uv run coverage report

# Frontend tests
bun test
```

### Linting and Formatting

```bash
# Python - ALWAYS run after changes
uv run ruff check . --fix
uv run ruff format .

# TypeScript/JavaScript
bun lint          # Check only
bun lint-fix      # Fix issues

# Django templates (Jinja2)
uv run djlint . --extension=j2 --check
uv run djlint . --extension=j2 --lint

# Run all pre-commit hooks
uv run pre-commit run --all-files
```

### Building

```bash
bun run build  # Build frontend assets (required before E2E tests)
```

## Architecture

### Django Monolith with API-First Approach

The project uses Django with Django Ninja for APIs. Despite using Django templates with SSR for the frontend, the API is used behind the scenes for data access.

### Application Structure

```text
sbomify/
├── apis.py           # Main API router (Django Ninja)
├── settings.py       # Django settings
├── apps/
│   ├── core/         # Dashboard, shared components, user management
│   ├── sboms/        # SBOM upload, storage, format handling
│   ├── documents/    # Document artifact management
│   ├── teams/        # Workspaces (teams), permissions, members
│   ├── billing/      # Subscription plans, Stripe integration
│   ├── plugins/      # Assessment plugins (NTIA, CRA, etc.)
│   ├── vulnerability_scanning/  # OSV, Dependency Track integration
│   ├── access_tokens/  # API authentication tokens
│   ├── licensing/    # License validation
│   ├── notifications/  # User notifications
│   └── onboarding/   # User onboarding flow
```

### Frontend Architecture

- **Templates**: Django/Jinja2 templates (`.html.j2` extension)
- **JavaScript**: TypeScript with Alpine.js for interactivity
- **Build**: Vite bundles JS per app (`sbomify/apps/*/js/main.ts`)
- **Styling**: Bootstrap (potential migration to Tailwind)
- **Package manager**: Bun

Entry points defined in `vite.config.ts`:

- core, sboms, teams, billing, documents, vulnerability_scanning, plugins

### Background Tasks

Uses Dramatiq with Redis for async task processing (vulnerability scanning, assessments).

### Storage

- **Database**: PostgreSQL
- **Object Storage**: S3-compatible (Minio for development)
  - Separate buckets for media, SBOMs, and documents
- **Caching**: Redis

### Authentication

- **Development**: Keycloak (auto-bootstrapped via Docker)
- **Production**: Keycloak with django-allauth

## Key Conventions

### Naming

- "sbomify" is always lowercase
- "Workspace" in code/UI maps to "Team" in models (legacy naming)

### Python

- Python 3.13+, type hints required
- Use modern Python features: f-strings, `|` for union types, walrus operator where appropriate
- Use `uv run` to execute Python commands
- pytest for all tests (never unittest)
- Use fixtures pattern, pytest-mock for mocking

### TypeScript

- All JavaScript must be TypeScript
- Use Bun as runtime and test runner
- Prefer interfaces over types
- Avoid enums, use maps instead

### Django

- Django Ninja for new API development
- Class-based views for complex views, function-based for simple
- Templates end with `.html.j2`
- Never edit existing migration files

### Code Quality

- Fix linting errors, don't annotate to skip them
- Never use `# noqa` or `# type: ignore` - fix the actual problem instead
- Never leave commented-out code
- 80% minimum test coverage
- Security-paranoid: validate input, use environment variables for secrets

## ADR Summary

- **ADR-001**: Django monolith with API-first approach (moved away from Vue SPA)
- **ADR-002**: Python with type hints + TypeScript; uv/Bun for package management
- **ADR-003**: Plugin-based assessment system for SBOM analysis (NTIA, OSV, etc.)
- **ADR-004**: Immutable artifacts - sbomify never modifies uploaded SBOMs/documents

## API Documentation

Available at `http://localhost:8000/api/v1/docs` when running locally.

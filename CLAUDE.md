# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

sbomify is a Software Bill of Materials (SBOM) and document management platform. It supports both CycloneDX and SPDX formats, vulnerability scanning, compliance assessments, and document artifact management.

**Key principle**: sbomify never modifies security artifacts (ADR-004). Artifacts are stored exactly as received — immutable. All analysis (vulnerability scanning, compliance checking) produces separate output without altering the original artifact.

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

Always run tests in Docker:

```bash
# Start test services
docker compose -f docker-compose.tests.yml up -d

# All tests (parallel — requires pytest-xdist installed in container)
docker compose -f docker-compose.tests.yml exec tests uv run pytest -n auto --ignore=sbomify/apps/core/tests/e2e

# All tests (sequential)
docker compose -f docker-compose.tests.yml exec tests uv run pytest --ignore=sbomify/apps/core/tests/e2e

# Specific file or directory
docker compose -f docker-compose.tests.yml exec tests uv run pytest sbomify/apps/sboms/tests/

# Single test with debugger
docker compose -f docker-compose.tests.yml exec tests uv run pytest --pdb -x -s sbomify/apps/sboms/tests/test_upload.py::test_name

# Coverage report (must be >= 80%)
docker compose -f docker-compose.tests.yml exec tests uv run coverage run -m pytest
docker compose -f docker-compose.tests.yml exec tests uv run coverage report
```

If tests fail with `database "test_sbomify_test" already exists` or `is being accessed by other users` (stale DB from killed parallel runs), clean up:

```bash
# Kill stale connections and drop test DB
docker compose -f docker-compose.tests.yml exec db psql -U sbomify_test -d postgres \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname LIKE 'test%' AND pid <> pg_backend_pid();"
docker compose -f docker-compose.tests.yml exec db psql -U sbomify_test -d postgres \
  -c "DROP DATABASE IF EXISTS test_sbomify_test;"

# If connections persist, restart the DB container
docker compose -f docker-compose.tests.yml restart db
# Wait for it, then drop
docker compose -f docker-compose.tests.yml up -d
sleep 15
docker compose -f docker-compose.tests.yml exec db psql -U sbomify_test -d postgres \
  -c "DROP DATABASE IF EXISTS test_sbomify_test;"
```

E2E tests use Playwright via Chrome DevTools Protocol in Docker with visual regression (baseline screenshots in `__snapshots__/`, diffs in `__diffs__/`):

```bash
docker compose -f docker-compose.tests.yml exec tests uv run pytest sbomify/apps/core/tests/e2e/
```

Frontend tests:

```bash
bun test
bun test path/to/file.spec.ts
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

# After CSS/frontend changes in Docker environment
bun run copy-deps && bun x vite build
uv run python manage.py collectstatic --noinput
```

### Running Django Commands in Docker

```bash
docker exec sbomify-backend-1 uv run python manage.py <command>
# If container name differs, find it with: docker ps
```

## Architecture

### Django Monolith with API-First Approach

Django with Django Ninja for APIs. The frontend is server-driven — data comes from Django Views via template context, not client-side fetch/API calls. Despite SSR, the internal API is used behind the scenes for data access (ADR-001).

### Service Layer Pattern

Views must NOT access the ORM directly. All data access goes through service functions that return `ServiceResult[T]` (from `sbomify.apps.core.services.results`):

```python
# Service function
def build_context(request: HttpRequest, id: str) -> ServiceResult[dict]:
    status_code, data = some_api_call(request, id)
    if status_code != 200:
        return ServiceResult.failure(data.get("detail", "Error"))
    return ServiceResult.success({"key": data})

# View usage
result = build_context(request, id)
if not result.ok:
    return htmx_error_response(result.error or "Unknown error")
return render(request, "template.html.j2", result.value)
```

### Frontend Architecture (ADR-005)

| Layer | Technology | Responsibility |
| ------- | --------- | -------------- |
| Structure | Django/Jinja2 templates (`.html.j2`) | HTML generation, server-side logic |
| Styling | Tailwind CSS | Visual presentation via `tw-*` component classes |
| State | Alpine.js | Component state, client-side interactivity |
| Updates | HTMX | Partial page updates, form submissions |

Key patterns:

- **Tailwind component classes**: `tw-btn-primary`, `tw-badge-success`, `tw-form-input`, `tw-card-*`, `tw-data-table` — defined in `sbomify/assets/css/tailwind.src.css`
- **Jinja2 component macros**: Reusable UI in `sbomify/apps/core/templates/components/tw/` (button, card, modal, input, badge, etc.)
- **Server data to Alpine.js**: Use `{{ data|json_script:"id" }}` + `window.parseJsonScript('id')` — never client-side fetch
- **HTMX partials**: Views return partial HTML for HTMX requests; triggers like `hx-trigger="refresh-items from:body"`
- **Dark mode**: `.dark` class on `<html>` element (not `[data-bs-theme]`)
- **Component reference**: The tw-tests page at `/tailwind-test/` is the source of truth for all component patterns
- **Vite entry points** in `vite.config.ts`: core, sboms, teams, billing, documents, vulnerability_scanning, plugins

> **Migration note**: Bootstrap and Tailwind coexist during transition. New components use Tailwind exclusively. Bootstrap is removed once all pages are converted.

### API Layer

Central router in `sbomify/apis.py` registers per-app routers. Each app has an `apis.py` with a `Router()`:

```python
# Dual auth on every endpoint: session (web) + personal access token (API)
from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from ninja.security import django_auth

@router.get("/{id}", auth=(PersonalAccessTokenAuth(), django_auth),
            response={200: ItemSchema, 404: ErrorResponse})
def get_item(request, id: str):
    ...
```

Register new app APIs in `sbomify/apis.py`:

```python
api.add_router("/your-app", "sbomify.apps.your_app.apis.router")
```

### Plugin/Assessment System (ADR-003)

Plugins analyze SBOMs without modifying them:

1. Subclass `AssessmentPlugin` from `sbomify.apps.plugins.sdk`
2. Implement `get_metadata()` and `assess(sbom_id, sbom_path)` methods
3. Framework handles S3 fetch, temp file, and cleanup — plugins just read the file
4. Return `AssessmentResult`; results stored immutably in `AssessmentRun`
5. See `sbomify/apps/plugins/builtins/ntia.py` for reference implementation

`PluginOrchestrator` (`sbomify/apps/plugins/orchestrator.py`) manages execution, dependency checking, config hashing, and retry logic (`RetryLaterError`).

### WebSockets

Django Channels with Redis for real-time broadcasting. Routing in `sbomify/apps/core/routing.py`, consumers in `consumers.py`. Service functions call `broadcast_to_workspace()` to push updates that trigger HTMX refreshes.

### Background Tasks

Dramatiq with Redis for async processing (vulnerability scanning, assessments). Tasks live in `sbomify/apps/*/tasks/`.

### Storage

- **Database**: PostgreSQL 17
- **Object Storage**: S3-compatible (Minio for development) — separate buckets for media, SBOMs, documents
- **Caching/Broker**: Redis 8

### Authentication

Keycloak with django-allauth. Auto-bootstrapped via Docker in development.

## Key Conventions

### Naming

- "sbomify" is always lowercase
- "Workspace" in UI maps to "Team" in models (legacy naming)

### Python

- Python 3.13+, type hints required
- Modern syntax: f-strings, `|` for union types, walrus operator
- `uv run` to execute all Python commands
- pytest only (never unittest); fixtures pattern, pytest-mock for mocking
- Never manually edit lockfiles — use `uv` or `bun`

### TypeScript

- All JavaScript must be TypeScript
- Bun as runtime and test runner
- Prefer interfaces over types; avoid enums, use maps
- kebab-case file naming (e.g., `plan-card.ts`, `plan-card.spec.ts`)
- CSRF tokens: import from `sbomify/apps/core/js/csrf.ts`

### Django Views

- **Class-Based Views only** — function-based views are not allowed
- Data access via service functions only — views must not touch the ORM
- Validation via Django Forms, submission via HTMX, client behavior via Alpine.js
- Templates end with `.html.j2`; use `{% url 'app:view' %}` — never hardcode paths
- Never edit existing migration files

### Code Quality

- Fix linting errors — never use `# noqa` or `# type: ignore`
- Never leave commented-out code
- Avoid unnecessary comments and logs
- 80% minimum test coverage
- Use `gh` CLI for GitHub operations

## ADR Summary

- **ADR-001**: Django monolith with API-first approach (moved away from Vue SPA)
- **ADR-002**: Python with type hints + TypeScript; uv/Bun for package management
- **ADR-003**: Plugin-based assessment system for SBOM analysis
- **ADR-004**: Immutable artifacts — sbomify never modifies uploaded SBOMs/documents
- **ADR-005**: Tailwind CSS + Alpine.js + HTMX frontend architecture (replacing Bootstrap)

## API Documentation

Available at `http://localhost:8000/api/v1/docs` when running locally.

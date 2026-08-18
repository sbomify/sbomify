# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

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

### Key Test Fixtures

Global fixtures (no import needed — registered in root `conftest.py`):

| Fixture                         | What it provides                                                            |
| ------------------------------- | --------------------------------------------------------------------------- |
| `sample_user`                   | Test user from `DJANGO_TEST_USER` env                                       |
| `guest_user`                    | Second standalone user (no team role assigned)                              |
| `sample_team`                   | Bare Team with no members                                                   |
| `sample_team_with_owner_member` | Owner `Member` for `sample_user` in `sample_team` (access team via `.team`) |
| `team_with_community_plan`      | Team + community billing plan                                               |
| `team_with_business_plan`       | Team + active business subscription                                         |
| `authenticated_api_client`      | `(Client, AccessToken)` tuple — use `get_api_headers(token)` for auth       |
| `authenticated_web_client`      | Django Client with full session for web tests                               |
| `ensure_billing_plans`          | Creates billing plan objects (use explicitly)                               |

Session setup helper: `setup_authenticated_client_session(client, team, user)` from `sbomify.apps.core.tests.shared_fixtures`.

Test settings: `sbomify.test_settings`. Tests run with `--nomigrations` (bare schema). Deselect slow tests: `-m "not slow"`.

### Linting and Formatting

```bash
# Python - ALWAYS run after changes
uv run ruff check . --fix
uv run ruff format .
uv run mypy .

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

### Domain Model Hierarchy

```text
Workspace (Team) → Product → Component → SBOM / Document
```

Components are the core unit — each can contain SBOMs and/or documents. Components attach directly to Products via a `ProductComponent` M2M. Releases are tagged collections of component artifacts under a Product. The `core` app has **proxy models** for entities whose tables live in `sboms`:

```python
from sbomify.apps.core.models import Product, Component  # use these in new code
```

Most entity PKs (Product, Component, SBOM, Document, Release) are 12-character alphanumeric tokens generated by `generate_id()` from `sbomify.apps.core.utils`. Team uses an auto-incrementing integer PK with a separate `key` field derived via `number_to_random_token(pk)`.

### Service Layer Pattern

Views must NOT access the ORM directly. All data access goes through service functions that return `ServiceResult[T]` (from `sbomify.apps.core.services.results`):

```python
@dataclass(frozen=True)
class ServiceResult(Generic[T]):
    value: T | None = None
    error: str | None = None
    status_code: int | None = None  # optional HTTP status for error propagation

    @property
    def ok(self) -> bool: ...
    @classmethod
    def success(cls, value: T | None = None) -> "ServiceResult[T]": ...
    @classmethod
    def failure(cls, error: str, status_code: int | None = None) -> "ServiceResult[T]": ...
```

Usage in views:

```python
result = build_context(request, id)
if not result.ok:
    return htmx_error_response(result.error or "Unknown error")
return render(request, "template.html.j2", result.value)
```

### Domain Exceptions and HTMX Helpers

Typed exceptions in `sbomify.apps.core.domain.exceptions`:

| Exception              | Status | Use for                              |
| ---------------------- | ------ | ------------------------------------ |
| `DomainError`          | 400    | Base class                           |
| `ValidationError`      | 400    | Invalid input                        |
| `PermissionDeniedError`| 403    | Forbidden / insufficient permissions |
| `NotFoundError`        | 404    | Missing resource                     |
| `ConflictError`        | 409    | Duplicate/conflict                   |
| `ExternalServiceError` | 502    | Third-party failure                  |

HTMX response helpers in `sbomify.apps.core.htmx`:

```python
htmx_success_response(message, triggers=None, content=None)  # toast + optional HTMX triggers + optional payload
htmx_error_response(message, triggers=None, content=None)    # error toast + HX-Reswap: none
htmx_error_from_exception(error: DomainError)                # converts DomainError via content=error.to_dict()
```

### Frontend (UI)

| Layer     | Technology                                   | Responsibility                             |
| --------- | -------------------------------------------- | ------------------------------------------ |
| Structure | Components (`sbomify/templates/components/`) | The HTML every page composes               |
| Styling   | Tailwind utilities, inside components        | Visual presentation                        |
| State     | Alpine.js                                    | Component state, client-side interactivity |
| Updates   | HTMX                                         | Partial page updates, form submissions     |

**Pages compose components. They do not style.** A page may use layout
utilities (grid, flex, spacing) and nothing else. The moment you write a
styled control, a repeated visual pattern, or anything wanting its own class,
it belongs in `sbomify/templates/components/`.

```html
{# No load tag needed: <c-dir.name> works in any template #}
<c-tables.shell>
  <c-tables.toolbar>
    <c-tables.search id="things-search" label="Search things" x-model="search" />
  </c-tables.toolbar>
  <c-tables.table fixed>…</c-tables.table>
</c-tables.shell>

<c-buttons.primary size="sm" hx-get="{% url 'core:new_thing' %}">New thing</c-buttons.primary>
```

**Two references, both live, neither prose.** Browse `/design-system/`
(DEBUG-only, URL name `core:design_system`) to see every component rendered
with its variants. Read the component's own file for its parameters: each one
opens with a comment explaining what it is for and why it is built that way.
The gallery is built from the components, so a broken component breaks the
gallery first.

Adding to the library: a variant is a new file nesting the base and passing
`variant_class`; a modifier (size, state, density) is a prop. Ship it with a
gallery demo in `core/design_system.html.j2` in the same change.

Colour, radius, shadow and type come from the tokens in
`sbomify/assets/css/tailwind.src.css` (`:root` is dark, `:root.light`
overrides). Use token utilities (`bg-surface`, `text-text-muted`,
`border-border`) or arbitrary values referencing tokens
(`bg-[color-mix(in_oklab,var(--color-primary)_12%,transparent)]`). A raw hex
in a diff is a review blocker.

#### The things that actually break

- **Two utilities for one CSS property.** Tailwind resolves them by stylesheet
  order, not the order you wrote them. Prop-dependent utilities must render as
  ONE `{% if %}` segment covering every case.
- **A `{# … #}` comment spanning more than one line is not a comment.** Django's
  tag pattern is single-line, so the text renders on the page or becomes junk
  attributes. Use `{% comment %}…{% endcomment %}`.
- **`:class` on a `<c-*>` tag.** Cotton reads a leading `:` as its own dynamic-prop
  prefix, so Alpine's bindings there are written `::class` / `::style`. On plain
  HTML inside a component they pass through untouched.
- **An omitted `<c-vars>` prop is undefined, not empty.** `{% if class %}` is safe;
  `"x-"|add:class` raises `VariableDoesNotExist`.
- **A form control does not inherit `text-transform`.** The UA stylesheet resets it,
  so a label wrapped in a `<button>` drops out of its parent's casing.
- **State belongs on the real element.** `disabled` on the button, `:checked` on the
  input, `[aria-disabled]` on a link. Never a styled sibling.
- **State only the browser knows goes on a data attribute.** The component carries
  every recipe keyed by `data-*`, the caller binds the value
  (`<c-badges.dynamic ::data-variant="row.status_variant" />`). Never hand a page a
  class expression: Tailwind never compiles a computed class name.
- **Referencing a class that does not exist fails silently.** Grep before shipping.
- **Copy is part of the component.** See Copy under Key Conventions; in UI it is a
  review blocker, same as a raw hex.

#### Other

- **Server data to Alpine**: `{{ data|json_script:"id" }}` + `window.parseJsonScript('id')`, never client-side fetch
- **HTMX partials**: views return partial HTML for HTMX requests; triggers like `hx-trigger="refresh-items from:body"`
- **Theme**: `.dark` / `.light` class on `<html>`; dark is the default
- **Vite entry points** in `vite.config.ts`: core, sboms, teams, billing, documents, vulnerability_scanning, plugins (plus alerts, djangoMessages, htmxBundle, tailwind). Dev server runs on port **5170**
- **Changing an existing page**: it probably has an e2e snapshot. Change structure
  only, and if the baselines move, confirm every move was intended before
  regenerating them.
- **`tw-*` classes are the old layer.** Do not add callers and do not delete them;
  unmigrated pages still consume them.

### API Layer

Central router in `sbomify/apis.py` registers per-app routers. Most apps expose a `Router()` in `apis.py` (some use `api.py`, e.g. `licensing`):

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

Keycloak with django-allauth. Auto-bootstrapped via Docker in development. Requires `127.0.0.1 keycloak` in `/etc/hosts` for dev. Dev test users: `jdoe/foobar123` and `ssmith/foobar123`. Tests use Django's `force_login`, not Keycloak.

### Team Roles and Permissions

Supported roles (defined in `TEAMS_SUPPORTED_ROLES`): `"owner"`, `"admin"`, `"member"`, `"guest"`, and `"bot"` — the last reserved for OIDC Trusted Publishing synthetic identities and never assignable by a human. A `member_role_is_supported` CheckConstraint on `Member` enforces the set at the database, so a role the code does not know about can no longer be written (which is how `"member"` itself existed for years as a value matching no role check).

**`sbomify/apps/core/authz.py` is the single source of truth.** `can(actor, action, resource)` maps a named action to a capability tier; the tier tuples are the only place roles are enumerated. Two rules keep it simple:

1. **The ladder stays linear** — `guest ⊂ member ⊂ admin ⊂ owner`. No role may hold a capability a more-privileged role lacks. `test_role_ladder_is_upward_closed` enforces this.
2. **Granularity is added as a tier, never as a per-user permission bundle or per-resource ACL.**

Tiers: `OWNER_ONLY` (owner) ⊂ `ADMINISTER` = `DELETE` (owner + admin) ⊂ `MANAGE` = `READ_INTERNAL` (+ member) ⊂ `PUBLISH` = `READ_INTERNAL_OR_BOT` (+ bot).

`member` is the day-to-day contributor: create and edit products, components and releases, upload artifacts, cut releases, triage vulnerabilities. Two things are deliberately carved *out* of `MANAGE` and up to `ADMINISTER`, because they are outward-facing rather than routine: `product:set_visibility` / `component:set_visibility` (publishing to the trust center) and `component:manage_publishers` (an OIDC binding is a standing, non-expiring publish grant to an external repo). Admins are near-owners: the only capability they lack is deleting the workspace (`OWNER_ONLY`). The other owner-exclusive rule — *an admin may not remove an owner* — is relational rather than a tier, so it lives in the member-removal guards (`teams/views/__init__.py`, `teams/views/team_settings.py`) and must not be dropped when those gates are edited.

Prefer `can()` over new inline role checks. For views, CBV mixins in `sbomify.apps.teams.permissions`:

```python
from sbomify.apps.core.authz import ADMINISTER

class MyView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    allowed_roles = list(ADMINISTER)  # not a hardcoded ["owner", "admin"]
```

**`guest` is an external role and holds no capability tier at all.** A guest `Member` row is an ACL anchor for the trust-center access-request/NDA machinery, not a grant: guests reach restricted content solely through the attribute-based `component:access` path (`core/services/access_control.py`), never through a role check. `GuestAccessBlockedMixin` redirects guest members to the public workspace page. Do not add `guest` to a tier — if an external user needs to contribute, that is what the internal roles are for.

**Templates must not branch on `request.session.current_team.role`** — that is a cache with a 300s TTL. Use the capability flags from `core.context_processors.team_context`, which read the live `Member` row: `can_administer`, `can_manage`, `can_delete`, `is_owner`. User-facing role explanations live in `authz.ROLE_DESCRIPTIONS` and render on the workspace members tab.

## Key Conventions

### Naming

- "sbomify" is always lowercase
- "Workspace" in UI maps to "Team" in models (legacy naming)

### Copy (anything a user reads)

Covers UI strings, labels, hints, placeholders, empty states, toasts, error
messages and docs pages.

- **Never use an em dash (—) or an en dash (–) as punctuation.** Use a comma, a
  colon, a full stop, or split it into two sentences.
- Keep it short. One idea per sentence. Cut any word that does not change the
  meaning.
- Use plain words. "Fix" not "remediation", "version" not "release artifact
  revision", "delete" not "permanently remove".
- Say what the user does or gets, not how it works inside. Names of internal
  models, statuses and fields are not copy.
- Write a button as the action it performs: "Create advisory", not "Submit".

In UI this is a review blocker, same as a raw hex value.

### Python

- Python 3.13+, type hints required
- Modern syntax: f-strings, `|` for union types, walrus operator
- `uv run` to execute all Python commands
- pytest is the primary test runner; prefer pytest-style tests (fixtures, pytest-mock), but some existing tests use Django `TestCase`
- Never manually edit lockfiles — use `uv` or `bun`
- Ruff line-length is **120** (not 88/79)

### TypeScript

- All JavaScript must be TypeScript
- Bun as runtime and test runner
- Prefer interfaces over types; avoid enums, use maps
- kebab-case file naming (e.g., `plan-card.ts`, `plan-card.spec.ts`)
- CSRF tokens: import from `sbomify/apps/core/js/csrf.ts`

### Django Views

- Prefer **Class-Based Views** for new or significantly modified endpoints; existing FBVs may remain
- Prefer data access via service-layer functions; avoid direct ORM usage in views except for simple, well-justified cases
- Validation via Django Forms, submission via HTMX, client behavior via Alpine.js
- Templates end with `.html.j2`; use `{% url 'app:view' %}` — never hardcode paths
- Never edit existing migration files

### Code Quality

- Fix linting errors — avoid `# noqa` and `# type: ignore` unless strictly necessary and narrowly scoped
- Never leave commented-out code
- Avoid unnecessary comments and logs
- 80% minimum test coverage
- Use `gh` CLI for GitHub operations
- Never amend commits or force push — always create new commits

## Spotlight Search (navbar)

The search bar is a navigation palette first, an asset finder second. Every
navigable destination lives in **`sbomify/apps/core/data/spotlight_destinations.json`** —
adding a feature to the palette means appending one object there and nothing else.
The file's own header documents the fields; `sbomify/apps/core/spotlight.py` reads it,
and `test_spotlight.py` fails on a `url_name` that does not resolve, so a typo cannot
ship as a dead entry.

When you add a user-facing feature, add its destination in the same PR, and put the
words people actually type in `keywords` — including the ones the UI does not use
(someone searching "api key" should land on the tokens tab).

## ADR Summary

- **ADR-001**: Django monolith with API-first approach (moved away from Vue SPA)
- **ADR-002**: Python with type hints + TypeScript; uv/Bun for package management
- **ADR-003**: Plugin-based assessment system for SBOM analysis
- **ADR-004**: Immutable artifacts — sbomify never modifies uploaded SBOMs/documents
- **ADR-005**: Tailwind CSS + Alpine.js + HTMX frontend architecture (replacing Bootstrap)

## API Documentation

Available at `http://localhost:8000/api/v1/docs` when running locally.

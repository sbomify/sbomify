# Developer Documentation

## Overview

This document provides an introduction to the basic principles and technologies used in this project. It will guide you through the stack, tools, and setup required to get started with development.

## Running Containers

We use **Docker Compose** and **Docker** for running our containers. This simplifies managing the local environment and dependencies.

**Important: Add to `/etc/hosts`**

Before starting the development environment, you must add the following entry to your `/etc/hosts` file for Keycloak authentication to work:

```bash
127.0.0.1   keycloak
```

To set up your local environment, simply run:

```bash
docker-compose up
```

This command will handle starting all required services for development.

### Environment Variables

When using `docker-compose.dev.yml`, the following development-specific environment variables are automatically configured:

- `LOCAL_DEV=True`: Enables local development mode, which allows Django to accept requests from any hostname (wildcards in `ALLOWED_HOSTS`). This is separate from `DEBUG` for security reasons - `LOCAL_DEV` should only be enabled on your local development machine, never in staging or production, even if `DEBUG` is temporarily enabled for troubleshooting.
- `DEBUG=True`: Enables Django debug mode
- `USE_VITE_DEV_SERVER=True`: Enables hot module reloading for frontend development

These variables are set in the `x-dev-env` anchor in `docker-compose.dev.yml` and are automatically applied to relevant services.

## Stack Overview

### Backend

- **Language/Framework**: The backend is written in **Python** using the **Django** framework.
- **Package Manager**: We use **uv** to manage Python packages.

### Dependencies

The Python backend relies on the following services:

1. **PostgreSQL**: Used as the database.
2. **Blob Storage**: We use **MinIO**, an S3-compatible storage server.

These services can either be run inside Docker Compose or directly on your local machine. Even when running the Python backend locally, it's recommended to use Docker Compose for spinning up the supporting services (e.g., PostgreSQL and MinIO). Ensure your environment file is properly configured when doing so.

### Frontend

- **Language/Framework**: The frontend is written in **TypeScript**, with Tailwind for CSS.
- **Runtime**: We use **Bun** to manage the JavaScript environment.

To start the development server:

```bash
bun run dev
```

Ensure that Bun is installed before proceeding.

## Card Components

We have implemented a unified card component system to ensure consistency across the application using Django templates with HTMX and Alpine.js.

### Available Components

**Standard Card Structure**
Use HTML with the appropriate CSS classes:

```html
<div class="card settings-card" data-shadow="md">
  <div class="card-header">
    <h5 class="card-title mb-0">Card Title</h5>
  </div>
  <div class="card-body">
    <!-- Content -->
  </div>
</div>
```

**Dashboard Card Structure**
For dashboard tables and lists:

```html
<div class="card dashboard-card">
  <div class="card-header">
    <div class="d-flex justify-content-between align-items-center">
      <h5>Title</h5>
      <button class="btn btn-primary">Action</button>
    </div>
  </div>
  <div class="card-body">
    <!-- Content -->
  </div>
</div>
```

**DangerZone Card Structure**
For dangerous actions that require special styling:

```html
<div class="card dangerzone-card">
  <div class="card-header">
    <h5 class="card-title mb-0">
      <i class="fas fa-exclamation-triangle me-2"></i>Danger Zone
    </h5>
  </div>
  <div class="card-body p-0">
    <div class="danger-section delete-section">
      <div class="section-header">
        <div class="section-icon delete-icon">
          <i class="fas fa-trash-alt"></i>
        </div>
        <div class="section-content">
          <h6 class="section-title">Delete Item</h6>
          <p class="section-description">Permanently remove this item</p>
        </div>
      </div>
      <button class="btn btn-danger modern-btn delete-btn">
        <i class="fas fa-trash-alt me-2"></i>Delete
      </button>
    </div>
  </div>
</div>
```

### CSS Classes and Variants

**Card Variants:**

- `settings-card`: For settings/configuration pages
- `dashboard-card`: For dashboard tables and lists
- `data-table`: For cards containing tables
- `modal-card`: For modal-style cards
- `dangerzone-card`: For dangerous actions (deletions, transfers, etc.)

**Shadow Options (data attributes):**

- `data-shadow="sm"`: Small shadow
- `data-shadow="md"`: Medium shadow
- `data-shadow="lg"`: Large shadow

**DangerZone CSS Classes:**

- `danger-section`: Base class for danger zone sections
- `delete-section`: Red-themed section for delete actions
- `transfer-section`: Orange-themed section for transfer actions
- `section-header`: Container for section icon and content
- `section-icon`: Icon container (use `delete-icon` or `transfer-icon`)
- `section-content`: Text content container
- `section-title`: Section heading
- `section-description`: Section description text
- `modern-btn`: Modern button styling
- `delete-btn`: Red button for delete actions
- `transfer-btn`: Orange button for transfer actions

### Migration Guide

**Before (Raw HTML):**

```html
<div class="card">
  <div class="card-header">
    <h5 class="card-title">Title</h5>
  </div>
  <div class="card-body">
    Content
  </div>
</div>
```

**After (Django Template with proper CSS classes):**

```html
<div class="card settings-card" data-shadow="md">
  <div class="card-header">
    <h5 class="card-title mb-0">Title</h5>
  </div>
  <div class="card-body">
    Content
  </div>
</div>
```

### Best Practices

1. Use HTML structure with proper CSS classes in Django templates
2. Choose the appropriate card variant for your use case
3. **Use DangerZone Cards for destructive actions**:
   - Use `dangerzone-card` class for delete, transfer, or other potentially destructive operations
   - Include appropriate warning icons (`fas fa-exclamation-triangle` in header)
   - Structure content in `danger-section` divs with proper semantic classes
4. Use Alpine.js for interactive components (collapsible behavior, modals)
5. Use HTMX for server-driven updates without full page reloads
6. Maintain consistent shadow and spacing usage

### Implemented DangerZone Components

The dangerzone components use Django templates with HTMX/Alpine.js. The following templates are available in `sbomify/apps/core/templates/components/`:

- **Components**: `component_danger_zone.html.j2` (transfer + delete functionality)
- **Projects**: `project_danger_zone.html.j2` (delete only)
- **Products**: `product_danger_zone.html.j2` (delete only)
- **Releases**: `release_danger_zone.html.j2` (delete only)
- **SBOMs**: `sbom_danger_zone.html.j2` (delete only)
- **Workspaces**: `teams/components/team_danger_zone.html.j2` (delete only)

Each component uses Alpine.js for collapsible behavior and HTMX-based confirmation modals with consistent styling patterns.

### Important Notes

- All components use Django templates (server-rendered)
- Alpine.js is used for client-side interactivity (state, collapsible behavior)
- HTMX is used for server-driven updates
- Always test functionality after making changes to ensure cards render correctly

## Development Standards

### Python Backend

1. **Linting**: All Python code must pass linting.
2. **Testing**: Unit tests and integration tests are mandatory for all Python code.

### JavaScript Development

1. **TypeScript**: All frontend code must be written in TypeScript to catch issues early.
2. **Linting**: Frontend code is linted using Bun.

## Error Tracking

We use **Sentry** to catch and track bugs in both the backend and frontend. Ensure that your code references Sentry correctly to capture errors.

## Getting Started

1. Run `docker-compose up` to start all necessary services.
2. Configure your environment file as needed.
3. Install dependencies for:
   - Python: Use `uv sync`.
   - JavaScript: Install Bun and run `bun install`.
4. Run the backend or frontend as needed, ensuring proper linting and tests are in place.

Follow these principles and standards to ensure smooth development and maintain high code quality.

### Tests & Code Quality

#### Python

- Linting: `uv run ruff check && uv run ruff format`
- Tests: `uv run pytest`

#### TypeScript

- Linting: `bun run lint`
- Tests: `bun test`

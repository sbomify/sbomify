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

We have implemented a unified card component system to ensure consistency across the application. The approach differs between Django templates (server-rendered) and Vue components (client-rendered).

### Available Components

#### For Vue Components

**StandardCard (`vc-standard-card`)**
The main card component with multiple variants:

```vue
<StandardCard
  title="Card Title"
  variant="settings"
  size="large"
  :collapsible="true">
  <template #header-actions>
    <button class="btn btn-primary">Action</button>
  </template>
  <!-- Content -->
</StandardCard>
```

**DangerZone Card**
For dangerous actions like deletions and transfers:

```vue
<StandardCard
  title="Danger Zone"
  variant="dangerzone"
  :collapsible="true"
  :defaultExpanded="false"
  storageKey="danger-zone"
  infoIcon="fas fa-exclamation-triangle">
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
</StandardCard>
```

**StatCard (`vc-stat-card`)**
Specialized for displaying statistics and metrics:

```vue
<StatCard
  title="Active Users"
  :value="1234"
  subtitle="Last 30 days"
  trend="positive"
  color-scheme="primary"
/>
```

**PlanCard (`vc-plan-card`)**
Specialized for billing plans and pricing:

```vue
<PlanCard
  plan-name="Professional"
  :price="29"
  price-period="month"
  :features="['Feature 1', 'Feature 2']"
  button-text="Choose Plan"
/>
```

#### For Django Templates

**Standard Card Structure**
Use HTML with the appropriate CSS classes that match our Vue components:

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

**After (Django Template):**

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

**After (Vue Component):**

```vue
<StandardCard title="Title" variant="settings" shadow="md">
  Content
</StandardCard>
```

**DangerZone Migration (Vue Component):**

```vue
<!-- Before: Custom danger zone styling -->
<div class="card border-danger">
  <div class="card-header bg-danger text-white">
    <h5>Danger Zone</h5>
  </div>
  <!-- Content -->
</div>

<!-- After: StandardCard with dangerzone variant -->
<StandardCard
  title="Danger Zone"
  variant="dangerzone"
  :collapsible="true"
  :defaultExpanded="false"
  infoIcon="fas fa-exclamation-triangle">
  <!-- Content -->
</StandardCard>
```

### Best Practices

1. **Django Templates**: Use HTML structure with proper CSS classes
2. **Vue Components**: Use the provided Vue components (StandardCard, StatCard, PlanCard)
3. Choose the appropriate variant for your use case
4. Use StatCard for metrics and dashboard stats
5. Use PlanCard for pricing/billing displays
6. **Use DangerZone Cards for destructive actions**:
   - Always use `variant="dangerzone"` for delete, transfer, or other potentially destructive operations
   - Include appropriate warning icons (`fas fa-exclamation-triangle` in header)
   - Use collapsible behavior (`defaultExpanded="false"`) to prevent accidental clicks
   - Structure content in `danger-section` divs with proper semantic classes
7. Leverage slots for complex header actions or custom content
8. Maintain consistent shadow and spacing usage

### Implemented DangerZone Components

The following dangerzone components are available and use the `variant="dangerzone"` theming:

- **Components**: `vc-danger-zone` (transfer + delete functionality)
- **Projects**: `vc-project-danger-zone` (delete only)
- **Products**: `vc-product-danger-zone` (delete only)
- **Teams/Workspaces**: `vc-team-danger-zone` (delete only)

Each component implements collapsible behavior, confirmation modals, and consistent styling patterns.

### Important Notes

- Vue components (`vc-standard-card`, `vc-stat-card`, etc.) only work within Vue applications
- Django templates are server-rendered and require HTML structure
- Both approaches use the same underlying CSS for consistent styling
- **DangerZone Cards**: The `dangerzone` variant provides card-level theming (red border, warning header), while section content styling is handled by individual components due to CSS scoping
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

# Developer Documentation

## Overview

This document provides an introduction to the basic principles and technologies used in this project. It will guide you through the stack, tools, and setup required to get started with development.

## Running Containers

We use **Docker Compose** and **Docker** for running our containers. This simplifies managing the local environment and dependencies. To set up your local environment, simply run:

```bash
docker-compose up
```

This command will handle starting all required services for development.

## Stack Overview

### Backend

- **Language/Framework**: The backend is written in **Python** using the **Django** framework.
- **Package Manager**: We use **poetry** to manage Python packages.

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

### CSS Classes and Variants

**Card Variants:**

- `settings-card`: For settings/configuration pages
- `dashboard-card`: For dashboard tables and lists
- `data-table`: For cards containing tables
- `modal-card`: For modal-style cards

**Shadow Options (data attributes):**

- `data-shadow="sm"`: Small shadow
- `data-shadow="md"`: Medium shadow
- `data-shadow="lg"`: Large shadow

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

### Best Practices

1. **Django Templates**: Use HTML structure with proper CSS classes
2. **Vue Components**: Use the provided Vue components (StandardCard, StatCard, PlanCard)
3. Choose the appropriate variant for your use case
4. Use StatCard for metrics and dashboard stats
5. Use PlanCard for pricing/billing displays
6. Leverage slots for complex header actions or custom content
7. Maintain consistent shadow and spacing usage

### Important Notes

- Vue components (`vc-standard-card`, `vc-stat-card`, etc.) only work within Vue applications
- Django templates are server-rendered and require HTML structure
- Both approaches use the same underlying CSS for consistent styling
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
   - Python: Use `poetry install`.
   - JavaScript: Install Bun and run `bun install`.
4. Run the backend or frontend as needed, ensuring proper linting and tests are in place.

Follow these principles and standards to ensure smooth development and maintain high code quality.

### Tests & Code Quality

#### Python

- Linting: `poetry run ruff check && poetry run ruff format`
- Tests: `poetry run pytest`

#### TypeScript

- Linting: `bun run lint`
- Tests: `bun test`

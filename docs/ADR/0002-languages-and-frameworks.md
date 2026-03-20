# 2. Languages and Frameworks

Date: 2024-01-01

## Status

Accepted

## Context

sbomify needs consistent choices for programming languages, frameworks, package management, and testing across both backend and frontend. Static typing and managed dependencies are priorities for maintainability and security (we cannot manage vulnerabilities nor generate SBOMs without a package manager).

## Decision

As a rule of thumb, we shall always use static typing where it is an option.

For all external libraries and dependencies, we shall always use a package manager regardless of the language. Linting shall be used regardless of language.

### Backend

- For the backend, we shall use Python with type hints.
- For package management, we are using UV.
- As outlined in ADR-001, Django shall be used.
- For tests, we are using pytest.

### Frontend

- All JavaScript shall be written as TypeScript.
- Front-end code shall be tested using Bun's test runner.
- For the package manager, we are using Bun.
  - Avoid calling external JavaScript from the codebase; instead, use packages managed by the package manager.
- As per ADR-001, the front-end shall use Django Templates, but we will still rely on JavaScript components.
- For styling, we are migrating from Bootstrap to Tailwind CSS (see ADR-005 for full architecture).
- For client-side reactivity, we use Alpine.js with HTMX for server-driven updates (see ADR-005).

### Runtime

To minimize the delta between development, staging, and production, all environments shall be running in Docker (or Podman) using the `docker compose` files.

You may choose to run things without containers when developing, but you shall always test that things work with Docker.

### Authentication

For authentication, we are using [Keycloak](https://www.keycloak.org/). This is spun up and automatically bootstrapped if you are using the developer environment.

## Consequences

- Static typing and linting catch errors early
- Consistent package management enables SBOM generation and vulnerability tracking for our own dependencies
- Docker-based environments reduce environment drift between development and production
- Developers need familiarity with both Python/Django and TypeScript/Bun toolchains

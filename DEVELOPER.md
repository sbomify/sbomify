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
- Tests: `bun vitest`

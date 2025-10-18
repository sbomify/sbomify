# Base Python version
ARG PYTHON_VERSION=3.12-slim-bookworm@sha256:9c1d9ed7593f2552a4ea47362ec0d2ddf5923458a53d0c8e30edf8b398c94a31
ARG BUILD_ENV=production # Default to production
ARG OSV_SCANNER_VERSION=v2.0.2
ARG CYCLONEDX_GOMOD_VERSION=v1.9.0

### Stage 1: Bun JS build for Production Frontend Assets
FROM oven/bun:1.3-debian@sha256:386b9fd0974a0ad7d33a45c1f2e2ee7159da3807023868d0feb8b427af76b34e AS js-build-prod

WORKDIR /js-build

# Copy all frontend configuration files first
COPY package.json ./
COPY bun.lock ./
COPY tsconfig*.json ./
COPY vite.config.ts ./
COPY eslint.config.js ./
COPY .prettierrc.js ./

# Install dependencies
RUN bun install --frozen-lockfile --production

# Copy source files
COPY sbomify/apps/core/js/ ./sbomify/apps/core/js/
COPY sbomify/apps/sboms/js/ ./sbomify/apps/sboms/js/
COPY sbomify/apps/teams/js/ ./sbomify/apps/teams/js/
COPY sbomify/apps/billing/js/ ./sbomify/apps/billing/js/
COPY sbomify/apps/documents/js/ ./sbomify/apps/documents/js/
COPY sbomify/apps/vulnerability_scanning/js/ ./sbomify/apps/vulnerability_scanning/js/

# Copy existing static files
COPY sbomify/static/ ./sbomify/static/

# Create additional directories for build scripts
RUN mkdir -p sbomify/static/css sbomify/static/webfonts sbomify/static/dist

# Run the build for production - Vite now outputs to static/dist/
RUN bun run copy-deps && bun x vite build

### Stage 2: Frontend Development Server
FROM oven/bun:1.3-debian@sha256:386b9fd0974a0ad7d33a45c1f2e2ee7159da3807023868d0feb8b427af76b34e AS frontend-dev-server

WORKDIR /app-frontend

# Copy frontend configuration and source
COPY package.json ./
COPY bun.lock ./
COPY tsconfig*.json ./
COPY vite.config.ts ./
COPY eslint.config.js ./
COPY .prettierrc.js ./
COPY sbomify/apps/core/js/ ./sbomify/apps/core/js/
COPY sbomify/apps/sboms/js/ ./sbomify/apps/sboms/js/
COPY sbomify/apps/teams/js/ ./sbomify/apps/teams/js/
COPY sbomify/apps/billing/js/ ./sbomify/apps/billing/js/
COPY sbomify/apps/documents/js/ ./sbomify/apps/documents/js/
COPY sbomify/apps/vulnerability_scanning/js/ ./sbomify/apps/vulnerability_scanning/js/

# Install dependencies
RUN bun install --frozen-lockfile

# Expose Vite dev server port
EXPOSE 5170

# Command to run Vite dev server
CMD ["bun", "run", "dev"]


### Stage 3: Python Common Code Base
FROM python:${PYTHON_VERSION} AS python-common-code

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies & Poetry
RUN apt-get update && apt-get install -y \
    libpq-dev \
    redis-tools \
    postgresql-client \
    gcc \
    && rm -rf /var/lib/apt/lists/* \
    && pip install poetry

WORKDIR /code

# Copy project configuration and all application code
COPY pyproject.toml poetry.lock ./
COPY . .

### Stage 4: Python Dependencies
FROM python-common-code AS python-dependencies

ARG BUILD_ENV
ENV BUILD_ENV=${BUILD_ENV}

# Configure Poetry to use system Python and not create virtual environments
ENV POETRY_VENV_IN_PROJECT=false
ENV POETRY_NO_INTERACTION=1
ENV POETRY_CACHE_DIR=/tmp/poetry_cache

# Install Python dependencies based on BUILD_ENV
# This will also install the project package itself.
RUN if [ "${BUILD_ENV}" = "production" ]; then \
        echo "Installing production Python dependencies..."; \
        poetry install --only main,prod --no-interaction; \
    else \
        echo "Installing development Python dependencies (includes dev, test)..."; \
        poetry install --no-interaction; \
    fi

### Stage 5: Go Builder for OSV-Scanner
FROM golang:1.25-alpine@sha256:ecb803821dbac0983b03a516adb8407b7dbadfb8771434dc5162a7c471dd27a2 AS go-builder
ARG OSV_SCANNER_VERSION
ARG CYCLONEDX_GOMOD_VERSION

WORKDIR /src

# Install osv-scanner and generate SBOM
RUN go install github.com/google/osv-scanner/v2/cmd/osv-scanner@${OSV_SCANNER_VERSION}

# Build SBOM
RUN go install github.com/CycloneDX/cyclonedx-gomod/cmd/cyclonedx-gomod@${CYCLONEDX_GOMOD_VERSION}
RUN /go/bin/cyclonedx-gomod bin -json -output /tmp/osv.cdx.json /go/bin/osv-scanner

### Stage 6: Python Application for Development (python-app-dev)
FROM python-dependencies AS python-app-dev

WORKDIR /code
# No production-specific asset copying or collectstatic needed for dev

# Copy the osv-scanner binary from the go-builder stage
COPY --from=go-builder /go/bin/osv-scanner /usr/local/bin/osv-scanner

# Create directories with proper permissions for non-root user
# Create dedicated directory for Prometheus metrics and ensure /tmp is writable for app processes
RUN mkdir -p /var/lib/dramatiq-prometheus && \
    chown nobody:nogroup /var/lib/dramatiq-prometheus /tmp && \
    chmod 755 /var/lib/dramatiq-prometheus && \
    chmod 755 /tmp

# Set environment variable to direct Prometheus metrics to our dedicated directory
ENV PROMETHEUS_MULTIPROC_DIR=/var/lib/dramatiq-prometheus

# Configure Poetry to not create virtual environments (dependencies already installed)
ENV POETRY_VENV_IN_PROJECT=false
ENV POETRY_NO_INTERACTION=1
ENV POETRY_CACHE_DIR=/tmp/poetry_cache

# Switch to non-root user
USER nobody

EXPOSE 8000
# CMD for Development (using uvicorn directly with reload for development)
CMD ["poetry", "run", "uvicorn", "sbomify.asgi:application", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-include", "*.j2", "--log-level", "info"]
### Stage 7: Python Application for Production (python-app-prod)
# This is the default final stage if no target is specified.
FROM python-dependencies AS python-app-prod

WORKDIR /code

# Copy the osv-scanner binary from the go-builder stage
COPY --from=go-builder /go/bin/osv-scanner /usr/local/bin/osv-scanner

# Production-specific steps
COPY --from=js-build-prod /js-build/sbomify/static/dist /code/sbomify/static/dist
# Copy other static files that may have been created during build
COPY --from=js-build-prod /js-build/sbomify/static/css /code/sbomify/static/css
COPY --from=js-build-prod /js-build/sbomify/static/webfonts /code/sbomify/static/webfonts

# Create directories and run collectstatic as root, then fix permissions
# Create dedicated directory for Prometheus metrics and ensure /tmp is writable for app processes
RUN mkdir -p /var/lib/dramatiq-prometheus /code/staticfiles && \
    poetry run python manage.py collectstatic --noinput && \
    chown nobody:nogroup /var/lib/dramatiq-prometheus /tmp && \
    chmod 755 /var/lib/dramatiq-prometheus && \
    chmod 755 /tmp

# Set environment variable to direct Prometheus metrics to our dedicated directory
ENV PROMETHEUS_MULTIPROC_DIR=/var/lib/dramatiq-prometheus

# Configure Poetry to not create virtual environments (dependencies already installed)
ENV POETRY_VENV_IN_PROJECT=false
ENV POETRY_NO_INTERACTION=1
ENV POETRY_CACHE_DIR=/tmp/poetry_cache

# Switch to non-root user
USER nobody

EXPOSE 8000
# CMD for Production - Using Gunicorn with Uvicorn worker as recommended by Django docs
CMD ["poetry", "run", "gunicorn", "sbomify.asgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--worker-class", "uvicorn_worker.UvicornWorker"]

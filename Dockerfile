# Base Python version
ARG PYTHON_VERSION=3.12-slim-bookworm@sha256:9c1d9ed7593f2552a4ea47362ec0d2ddf5923458a53d0c8e30edf8b398c94a31
ARG BUILD_ENV=production # Default to production
ARG OSV_SCANNER_VERSION=v2.0.2
ARG CYCLONEDX_GOMOD_VERSION=v1.9.0

### Stage 1: Bun JS build for Production Frontend Assets
FROM oven/bun:1.3-debian@sha256:ff851006c8b322761d53593e7a78c92d09ec0a6bc09a55f81c9861e614761d9a AS js-build-prod

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
FROM oven/bun:1.3-debian@sha256:ff851006c8b322761d53593e7a78c92d09ec0a6bc09a55f81c9861e614761d9a AS frontend-dev-server

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

# Install system dependencies & uv
RUN apt-get update && apt-get install -y \
    libpq-dev \
    redis-tools \
    postgresql-client \
    gcc \
    && rm -rf /var/lib/apt/lists/* \
    && pip install uv

WORKDIR /code

# Copy project configuration and all application code
COPY pyproject.toml uv.lock ./
COPY . .

### Stage 4: Python Dependencies
FROM python-common-code AS python-dependencies

ARG BUILD_ENV
ENV BUILD_ENV=${BUILD_ENV}

# Configure uv environment
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install Python dependencies based on BUILD_ENV
RUN if [ "${BUILD_ENV}" = "production" ]; then \
        echo "Installing production Python dependencies..."; \
        uv sync --locked --no-dev; \
    else \
        echo "Installing development Python dependencies (includes dev, test)..."; \
        uv sync --locked; \
    fi

### Stage 5: Go Builder for OSV-Scanner
FROM golang:1.25-alpine@sha256:d3f0cf7723f3429e3f9ed846243970b20a2de7bae6a5b66fc5914e228d831bbb AS go-builder
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
# Note: In development, .venv is writable by nobody to support editable installs and hot-reload
RUN mkdir -p /var/lib/dramatiq-prometheus /tmp/.cache && \
    chown -R nobody:nogroup /var/lib/dramatiq-prometheus /tmp /tmp/.cache /code/.venv && \
    chmod 755 /var/lib/dramatiq-prometheus && \
    chmod 755 /tmp && \
    chmod 755 /tmp/.cache

# Set environment variables for Prometheus metrics and UV cache
ENV PROMETHEUS_MULTIPROC_DIR=/var/lib/dramatiq-prometheus \
    UV_CACHE_DIR=/tmp/.cache/uv \
    HOME=/tmp

# Switch to non-root user
USER nobody

EXPOSE 8000
# CMD for Development (using uvicorn directly with reload for development)
CMD ["uv", "run", "uvicorn", "sbomify.asgi:application", \
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
# Note: In production, .venv stays owned by root for better security (app can't modify its own dependencies)
RUN mkdir -p /var/lib/dramatiq-prometheus /code/staticfiles /tmp/.cache && \
    uv run python manage.py collectstatic --noinput && \
    chown -R nobody:nogroup /var/lib/dramatiq-prometheus /tmp /tmp/.cache && \
    chmod 755 /var/lib/dramatiq-prometheus && \
    chmod 755 /tmp && \
    chmod 755 /tmp/.cache

# Set environment variables for Prometheus metrics and UV cache
ENV PROMETHEUS_MULTIPROC_DIR=/var/lib/dramatiq-prometheus \
    UV_CACHE_DIR=/tmp/.cache/uv \
    HOME=/tmp \
    UV_NO_SYNC=1

# Switch to non-root user
USER nobody

EXPOSE 8000
# CMD for Production - Using Gunicorn with Uvicorn worker as recommended by Django docs
CMD ["uv", "run", "gunicorn", "sbomify.asgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--worker-class", "uvicorn_worker.UvicornWorker"]

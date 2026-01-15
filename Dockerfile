# Base Python version
ARG PYTHON_VERSION=3.13-slim-trixie@sha256:1f3781f578e17958f55ada96c0a827bf279a11e10d6a458ecb8bde667afbb669
ARG BUILD_ENV=production # Default to production
ARG OSV_SCANNER_VERSION=v2.0.2

# Build metadata arguments (passed from CI/CD)
ARG BUILD_DATE=""
ARG GIT_COMMIT=""
ARG GIT_COMMIT_SHORT=""
ARG GIT_REF=""
ARG VERSION=""
ARG BUILD_TYPE=""

### Stage 0: Keycloak Theme Build (Fully Independent)
FROM oven/bun:1.3-debian@sha256:3da1c52799fc527af4c5969876734cbaddbf3e49479c601cfebdb0d7cbcc61b4 AS keycloak-build

WORKDIR /keycloak-build

# Copy Keycloak-specific files only
COPY keycloak/package.json ./
COPY keycloak/bun.lock* ./
COPY keycloak/tailwind.config.ts ./
COPY keycloak/themes/ ./themes/

# Install Keycloak dependencies and build
RUN bun install --frozen-lockfile && bun run build

### Stage 1: Bun JS build for Production Frontend Assets
FROM oven/bun:1.3-debian@sha256:b5cf5ca5dc3e2a02d805802ba089401c4beabf597daabbf35a17b8e82dc2f7bc AS js-build-prod

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
COPY sbomify/apps/plugins/js/ ./sbomify/apps/plugins/js/

# Copy existing static files
COPY sbomify/static/ ./sbomify/static/

# Create additional directories for build scripts
RUN mkdir -p sbomify/static/css sbomify/static/webfonts sbomify/static/dist

# Build main frontend assets (Keycloak is built separately in Stage 0)
RUN bun run copy-deps && bun x vite build

### Stage 2: Frontend Development Server
FROM oven/bun:1.3-debian@sha256:b5cf5ca5dc3e2a02d805802ba089401c4beabf597daabbf35a17b8e82dc2f7bc AS frontend-dev-server

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
COPY sbomify/apps/plugins/js/ ./sbomify/apps/plugins/js/

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
    && pip install --root-user-action=ignore uv

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

### Stage 5: Go Builder for OSV-Scanner and Cosign
FROM golang:1.25-alpine@sha256:ac09a5f469f307e5da71e766b0bd59c9c49ea460a528cc3e6686513d64a6f1fb AS go-builder
ARG OSV_SCANNER_VERSION
# For releases, see: https://github.com/sigstore/cosign/releases
ARG COSIGN_VERSION=v2.4.1

WORKDIR /src

# Install osv-scanner
RUN go install github.com/google/osv-scanner/v2/cmd/osv-scanner@${OSV_SCANNER_VERSION}

# Install cosign for attestation verification
RUN go install github.com/sigstore/cosign/v2/cmd/cosign@${COSIGN_VERSION}

### Stage 6: Python Application for Development (python-app-dev)
FROM python-dependencies AS python-app-dev

WORKDIR /code
# No production-specific asset copying or collectstatic needed for dev

# Copy the osv-scanner and cosign binaries from the go-builder stage
COPY --from=go-builder /go/bin/osv-scanner /usr/local/bin/osv-scanner
COPY --from=go-builder /go/bin/cosign /usr/local/bin/cosign

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

# Re-declare build metadata ARGs (required in each stage that uses them)
ARG BUILD_DATE=""
ARG GIT_COMMIT=""
ARG GIT_COMMIT_SHORT=""
ARG GIT_REF=""
ARG VERSION=""
ARG BUILD_TYPE=""

# OCI Image Spec labels for container metadata
LABEL org.opencontainers.image.title="sbomify" \
      org.opencontainers.image.description="Your Security Artifact Hub - Generate, manage, and share SBOMs and compliance documents" \
      org.opencontainers.image.url="https://github.com/sbomify/sbomify" \
      org.opencontainers.image.source="https://github.com/sbomify/sbomify" \
      org.opencontainers.image.vendor="sbomify" \
      org.opencontainers.image.licenses="Apache-2.0 WITH Commons-Clause-1.0" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.ref.name="${GIT_REF}" \
      com.sbomify.build.type="${BUILD_TYPE}"

WORKDIR /code

# Copy the osv-scanner and cosign binaries from the go-builder stage
COPY --from=go-builder /go/bin/osv-scanner /usr/local/bin/osv-scanner
COPY --from=go-builder /go/bin/cosign /usr/local/bin/cosign

# Production-specific steps
COPY --from=js-build-prod /js-build/sbomify/static/dist /code/sbomify/static/dist
# Copy other static files that may have been created during build
COPY --from=js-build-prod /js-build/sbomify/static/css /code/sbomify/static/css
COPY --from=js-build-prod /js-build/sbomify/static/webfonts /code/sbomify/static/webfonts
# Copy the compiled Keycloak theme CSS from the separate Keycloak build stage
COPY --from=keycloak-build /keycloak-build/themes/sbomify/login/resources/css /code/keycloak/themes/sbomify/login/resources/css

# Create directories and run collectstatic as root, then fix permissions
# Create dedicated directory for Prometheus metrics and ensure /tmp is writable for app processes
# Note: In production, .venv stays owned by root for better security (app can't modify its own dependencies)
RUN mkdir -p /var/lib/dramatiq-prometheus /code/staticfiles /tmp/.cache && \
    uv run python manage.py collectstatic --noinput && \
    chown -R nobody:nogroup /var/lib/dramatiq-prometheus /tmp /tmp/.cache && \
    chmod 755 /var/lib/dramatiq-prometheus && \
    chmod 755 /tmp && \
    chmod 755 /tmp/.cache

# Set environment variables for Prometheus metrics, UV cache, and build metadata
# Build metadata is exposed at runtime for version display in the application
ENV PROMETHEUS_MULTIPROC_DIR=/var/lib/dramatiq-prometheus \
    UV_CACHE_DIR=/tmp/.cache/uv \
    HOME=/tmp \
    UV_NO_SYNC=1 \
    SBOMIFY_BUILD_DATE="${BUILD_DATE}" \
    SBOMIFY_GIT_COMMIT="${GIT_COMMIT}" \
    SBOMIFY_GIT_COMMIT_SHORT="${GIT_COMMIT_SHORT}" \
    SBOMIFY_GIT_REF="${GIT_REF}" \
    SBOMIFY_VERSION="${VERSION}" \
    SBOMIFY_BUILD_TYPE="${BUILD_TYPE}"

# Switch to non-root user
USER nobody

EXPOSE 8000
# CMD for Production - Using Gunicorn with Uvicorn worker as recommended by Django docs
CMD ["uv", "run", "gunicorn", "sbomify.asgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--worker-class", "uvicorn_worker.UvicornWorker"]

# Base Python version
ARG PYTHON_VERSION=3.14-slim-trixie@sha256:584e89d31009a79ae4d9e3ab2fba078524a6c0921cb2711d05e8bb5f628fc9b9
ARG BUILD_ENV=production # Default to production
ARG OSV_SCANNER_VERSION=v2.3.3

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
COPY tailwind.config.js ./
COPY postcss.config.js ./
COPY eslint.config.js ./
COPY .prettierrc.js ./

# Install dependencies
RUN bun install --frozen-lockfile --production

# Copy JS source files
COPY sbomify/apps/core/js/ ./sbomify/apps/core/js/
COPY sbomify/apps/sboms/js/ ./sbomify/apps/sboms/js/
COPY sbomify/apps/teams/js/ ./sbomify/apps/teams/js/
COPY sbomify/apps/billing/js/ ./sbomify/apps/billing/js/
COPY sbomify/apps/documents/js/ ./sbomify/apps/documents/js/
COPY sbomify/apps/vulnerability_scanning/js/ ./sbomify/apps/vulnerability_scanning/js/
COPY sbomify/apps/plugins/js/ ./sbomify/apps/plugins/js/

# Copy templates for Tailwind CSS content scanning (@source directives)
COPY sbomify/apps/core/templates/ ./sbomify/apps/core/templates/
COPY sbomify/apps/sboms/templates/ ./sbomify/apps/sboms/templates/
COPY sbomify/apps/teams/templates/ ./sbomify/apps/teams/templates/
COPY sbomify/apps/billing/templates/ ./sbomify/apps/billing/templates/
COPY sbomify/apps/documents/templates/ ./sbomify/apps/documents/templates/
COPY sbomify/apps/vulnerability_scanning/templates/ ./sbomify/apps/vulnerability_scanning/templates/
COPY sbomify/apps/plugins/templates/ ./sbomify/apps/plugins/templates/
COPY sbomify/apps/onboarding/templates/ ./sbomify/apps/onboarding/templates/
COPY sbomify/templates/ ./sbomify/templates/

# Copy existing static files
COPY sbomify/static/ ./sbomify/static/

# Copy assets (includes Tailwind source CSS)
COPY sbomify/assets/ ./sbomify/assets/

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
COPY tailwind.config.js ./
COPY postcss.config.js ./
COPY eslint.config.js ./
COPY .prettierrc.js ./

# Install dependencies (before source files for better Docker layer caching)
RUN bun install --frozen-lockfile

# Copy JS source files
COPY sbomify/apps/core/js/ ./sbomify/apps/core/js/
COPY sbomify/apps/sboms/js/ ./sbomify/apps/sboms/js/
COPY sbomify/apps/teams/js/ ./sbomify/apps/teams/js/
COPY sbomify/apps/billing/js/ ./sbomify/apps/billing/js/
COPY sbomify/apps/documents/js/ ./sbomify/apps/documents/js/
COPY sbomify/apps/vulnerability_scanning/js/ ./sbomify/apps/vulnerability_scanning/js/
COPY sbomify/apps/plugins/js/ ./sbomify/apps/plugins/js/

# Copy templates for Tailwind CSS content scanning (@source directives)
COPY sbomify/apps/core/templates/ ./sbomify/apps/core/templates/
COPY sbomify/apps/sboms/templates/ ./sbomify/apps/sboms/templates/
COPY sbomify/apps/teams/templates/ ./sbomify/apps/teams/templates/
COPY sbomify/apps/billing/templates/ ./sbomify/apps/billing/templates/
COPY sbomify/apps/documents/templates/ ./sbomify/apps/documents/templates/
COPY sbomify/apps/vulnerability_scanning/templates/ ./sbomify/apps/vulnerability_scanning/templates/
COPY sbomify/apps/plugins/templates/ ./sbomify/apps/plugins/templates/
COPY sbomify/apps/onboarding/templates/ ./sbomify/apps/onboarding/templates/
COPY sbomify/templates/ ./sbomify/templates/

# Copy static files (needed for Tailwind CSS source)
COPY sbomify/static/ ./sbomify/static/

# Copy assets (includes Tailwind source CSS)
COPY sbomify/assets/ ./sbomify/assets/

# Expose Vite dev server port
EXPOSE 5170

# Command to run Vite dev server
CMD ["bun", "run", "dev"]


### Stage 3: Python Common Code Base
FROM python:${PYTHON_VERSION} AS python-common-code

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies & uv
# apt-get upgrade pulls in security patches for base image packages (openssl, libc6, libpq, etc.)
# Build-time: gcc + libpq-dev (for compiling psycopg2 C extension)
# Runtime: libpq5 (provided by libpq-dev, kept after purge)
# Debug tools (redis-tools, postgresql-client) only installed in dev stage
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    libpq-dev \
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

# Install Python dependencies based on BUILD_ENV, then remove build-only packages
# gcc/libpq-dev are only needed for compiling C extensions (psycopg2) during uv sync
# Mark libpq5 as manually installed so it survives the auto-remove of libpq-dev
RUN if [ "${BUILD_ENV}" = "production" ]; then \
        echo "Installing production Python dependencies..."; \
        uv sync --locked --no-dev; \
    else \
        echo "Installing development Python dependencies (includes dev, test)..."; \
        uv sync --locked; \
    fi && \
    apt-mark manual libpq5 && \
    apt-get purge -y --auto-remove gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

### Stage 5: Download pre-built binaries for OSV-Scanner and Cosign
FROM alpine:3.21 AS binary-downloader
ARG OSV_SCANNER_VERSION
# For releases, see: https://github.com/sigstore/cosign/releases
ARG COSIGN_VERSION=v2.6.2
ARG TARGETARCH

RUN set -e && apk add --no-cache curl && \
    ARCH="${TARGETARCH}" && \
    # Download osv-scanner and verify checksum
    curl -fsSL "https://github.com/google/osv-scanner/releases/download/${OSV_SCANNER_VERSION}/osv-scanner_linux_${ARCH}" \
        -o /usr/local/bin/osv-scanner && \
    curl -fsSL "https://github.com/google/osv-scanner/releases/download/${OSV_SCANNER_VERSION}/osv-scanner_SHA256SUMS" \
        -o /tmp/osv-scanner_SHA256SUMS && \
    cd /usr/local/bin && \
    grep "osv-scanner_linux_${ARCH}$" /tmp/osv-scanner_SHA256SUMS > /tmp/osv-checksum.txt && \
    sed -i "s|osv-scanner_linux_${ARCH}|osv-scanner|" /tmp/osv-checksum.txt && \
    sha256sum -c /tmp/osv-checksum.txt && \
    chmod +x /usr/local/bin/osv-scanner && \
    # Download cosign and verify checksum
    curl -fsSL "https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign-linux-${ARCH}" \
        -o /usr/local/bin/cosign && \
    curl -fsSL "https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign_checksums.txt" \
        -o /tmp/cosign_checksums.txt && \
    grep "cosign-linux-${ARCH}$" /tmp/cosign_checksums.txt > /tmp/cosign-checksum.txt && \
    sed -i "s|cosign-linux-${ARCH}|cosign|" /tmp/cosign-checksum.txt && \
    sha256sum -c /tmp/cosign-checksum.txt && \
    chmod +x /usr/local/bin/cosign && \
    rm -f /tmp/osv-scanner_SHA256SUMS /tmp/osv-checksum.txt /tmp/cosign_checksums.txt /tmp/cosign-checksum.txt

### Stage 6: Python Application for Development (python-app-dev)
FROM python-dependencies AS python-app-dev

WORKDIR /code

# Install debug/convenience tools only in dev (not in production image)
RUN apt-get update && apt-get install -y \
    redis-tools \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy the osv-scanner and cosign binaries from the binary-downloader stage
COPY --from=binary-downloader /usr/local/bin/osv-scanner /usr/local/bin/osv-scanner
COPY --from=binary-downloader /usr/local/bin/cosign /usr/local/bin/cosign

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
### Stage 7a: Collect static files (Debian-based build stage)
# Runs collectstatic so the Chainguard prod image doesn't need Django execution or a shell
FROM python-dependencies AS collectstatic

WORKDIR /code

# Copy built frontend assets and Keycloak theme CSS
COPY --from=js-build-prod /js-build/sbomify/static/dist /code/sbomify/static/dist
COPY --from=js-build-prod /js-build/sbomify/static/css /code/sbomify/static/css
COPY --from=js-build-prod /js-build/sbomify/static/webfonts /code/sbomify/static/webfonts
COPY --from=keycloak-build /keycloak-build/themes/sbomify/login/resources/css /code/keycloak/themes/sbomify/login/resources/css

# Prevent uv run from implicitly syncing
ENV UV_NO_SYNC=1

# Run collectstatic, then repoint venv Python symlinks to Chainguard paths (/usr/bin/python)
# The venv was built against Debian's /usr/local/bin/python3.14 which doesn't exist in Chainguard
RUN mkdir -p /code/staticfiles && \
    uv run python manage.py collectstatic --noinput && \
    cd /code/.venv/bin && \
    rm -f python python3 python3.14 && \
    ln -s /usr/bin/python python && \
    ln -s python python3 && \
    ln -s python python3.14 && \
    # Gather runtime shared libraries needed by psycopg2 (via libpq) into a flat dir
    # These are libpq's transitive deps: Kerberos, LDAP, SASL, zstd (not in Chainguard base)
    # Using cp -L to follow symlinks and get actual files
    mkdir -p /runtime-libs && \
    cp -L /usr/lib/*/libpq.so.5 \
          /usr/lib/*/libgssapi_krb5.so.2 \
          /usr/lib/*/libkrb5.so.3 \
          /usr/lib/*/libk5crypto.so.3 \
          /usr/lib/*/libcom_err.so.2 \
          /usr/lib/*/libkrb5support.so.0 \
          /usr/lib/*/libldap.so.2 \
          /usr/lib/*/liblber.so.2 \
          /usr/lib/*/libsasl2.so.2 \
          /usr/lib/*/libkeyutils.so.1 \
          /usr/lib/*/libzstd.so.1 \
          /runtime-libs/ && \
    # Pre-create runtime directories needed by the Chainguard prod image (which has no shell)
    mkdir -p /runtime-dirs/var/lib/dramatiq-prometheus /runtime-dirs/tmp/.cache

### Stage 7b: Python Application for Production (python-app-prod)
# Chainguard distroless runtime: no shell, no package manager, minimal attack surface.
# Python version must match the build stage since the venv's site-packages path is
# version-specific (lib/python3.X/site-packages/). Pinned by digest for reproducibility;
# free tier only has :latest tag — update digest when bumping Python version.
FROM cgr.dev/chainguard/python:latest@sha256:65679db7c6f5122377025dba932ecc9d6d8e3a8902a98d6b1bbce58821319cc8 AS python-app-prod

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

# Copy app code, .venv (with fixed symlinks), and collected static files
COPY --from=collectstatic /code /code

# Copy runtime shared libraries (libpq + transitive deps: Kerberos, LDAP, SASL, zstd)
# Gathered in the collectstatic stage from Debian's arch-specific dirs into a flat dir
COPY --from=collectstatic /runtime-libs/ /usr/lib/

# Copy Go binaries
COPY --from=binary-downloader /usr/local/bin/osv-scanner /usr/local/bin/osv-scanner
COPY --from=binary-downloader /usr/local/bin/cosign /usr/local/bin/cosign

# Copy pre-created runtime directories with correct ownership for nonroot (UID 65532)
# /tmp already exists with sticky bit (1777) in the Chainguard base image
COPY --from=collectstatic --chown=65532:65532 /runtime-dirs/var/lib/dramatiq-prometheus /var/lib/dramatiq-prometheus
COPY --from=collectstatic --chown=65532:65532 /runtime-dirs/tmp/.cache /tmp/.cache

# Set environment variables for Prometheus metrics and build metadata
# No UV_CACHE_DIR or UV_NO_SYNC needed — uv is not present in this image
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROMETHEUS_MULTIPROC_DIR=/var/lib/dramatiq-prometheus \
    HOME=/tmp \
    SBOMIFY_BUILD_DATE="${BUILD_DATE}" \
    SBOMIFY_GIT_COMMIT="${GIT_COMMIT}" \
    SBOMIFY_GIT_COMMIT_SHORT="${GIT_COMMIT_SHORT}" \
    SBOMIFY_GIT_REF="${GIT_REF}" \
    SBOMIFY_VERSION="${VERSION}" \
    SBOMIFY_BUILD_TYPE="${BUILD_TYPE}"

# Switch to non-root user (Chainguard's built-in nonroot, UID 65532)
USER nonroot

EXPOSE 8000
# CMD for Production — run gunicorn directly from the pre-built .venv (no uv needed)
# --graceful-timeout 30: Workers get 30s to finish requests on SIGTERM
# --timeout 120: Max time for a single request (2 min for large SBOM uploads)
CMD ["/code/.venv/bin/gunicorn", "sbomify.asgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--worker-class", "uvicorn_worker.UvicornWorker", \
     "--graceful-timeout", "30", \
     "--timeout", "120"]

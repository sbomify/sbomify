# Base Python version
ARG PYTHON_VERSION=3.14-slim-trixie@sha256:fb83750094b46fd6b8adaa80f66e2302ecbe45d513f6cece637a841e1025b4ca
ARG BUILD_ENV=production # Default to production
ARG OSV_SCANNER_VERSION=v2.3.8
# For releases, see: https://github.com/sigstore/cosign/releases
# Pin Cosign to a current release to pick up security fixes and ensure reproducible builds.
ARG COSIGN_VERSION=v3.1.1
# Chainguard distroless Python for production, pinned by digest for reproducibility.
# IMPORTANT: This image must provide the same Python minor version as PYTHON_VERSION above.
# To update: docker pull cgr.dev/chainguard/python:latest && docker inspect --format '{{index .RepoDigests 0}}'
ARG CHAINGUARD_PYTHON_IMAGE=cgr.dev/chainguard/python@sha256:33334c2bf93fd99e6b3c42b518cc44bb5277a954826cdb4f9275ef95818d7eb7
# Chainguard Wolfi base for the weasyprint-libs builder stage, pinned by
# digest so the builder image itself is reproducible. The actual .so
# versions still come from `apk add` against the live Wolfi repo at build
# time — Wolfi ships no repo-snapshot mechanism, but its package updates
# are ABI-stable security patches, so the copied libraries stay binary-
# compatible across rebuilds. Bump the digest below when you want to pick
# up newer patches.
# To update: docker pull cgr.dev/chainguard/wolfi-base:latest && docker inspect --format '{{index .RepoDigests 0}}'
ARG CHAINGUARD_WOLFI_BASE_IMAGE=cgr.dev/chainguard/wolfi-base@sha256:34977aa13765da89f60fee8fe5230e2bb1c55192df08e383c58221ee0d1277fb

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
COPY sbomify/apps/compliance/js/ ./sbomify/apps/compliance/js/

# Copy templates for Tailwind CSS content scanning (@source directives)
COPY sbomify/apps/core/templates/ ./sbomify/apps/core/templates/
COPY sbomify/apps/sboms/templates/ ./sbomify/apps/sboms/templates/
COPY sbomify/apps/teams/templates/ ./sbomify/apps/teams/templates/
COPY sbomify/apps/billing/templates/ ./sbomify/apps/billing/templates/
COPY sbomify/apps/documents/templates/ ./sbomify/apps/documents/templates/
COPY sbomify/apps/vulnerability_scanning/templates/ ./sbomify/apps/vulnerability_scanning/templates/
COPY sbomify/apps/plugins/templates/ ./sbomify/apps/plugins/templates/
COPY sbomify/apps/onboarding/templates/ ./sbomify/apps/onboarding/templates/
COPY sbomify/apps/compliance/templates/ ./sbomify/apps/compliance/templates/
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
COPY sbomify/apps/compliance/js/ ./sbomify/apps/compliance/js/

# Copy templates for Tailwind CSS content scanning (@source directives)
COPY sbomify/apps/core/templates/ ./sbomify/apps/core/templates/
COPY sbomify/apps/sboms/templates/ ./sbomify/apps/sboms/templates/
COPY sbomify/apps/teams/templates/ ./sbomify/apps/teams/templates/
COPY sbomify/apps/billing/templates/ ./sbomify/apps/billing/templates/
COPY sbomify/apps/documents/templates/ ./sbomify/apps/documents/templates/
COPY sbomify/apps/vulnerability_scanning/templates/ ./sbomify/apps/vulnerability_scanning/templates/
COPY sbomify/apps/plugins/templates/ ./sbomify/apps/plugins/templates/
COPY sbomify/apps/onboarding/templates/ ./sbomify/apps/onboarding/templates/
COPY sbomify/apps/compliance/templates/ ./sbomify/apps/compliance/templates/
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
# Debug tools (redis-tools, postgresql-client) are installed in dev stage only
# libpq-dev and gcc are needed for building C extensions during dependency installation
# WeasyPrint (used by sbomify.apps.compliance.services.pdf_service to convert
# CRA bundle markdown to PDF) needs Pango ≥1.4.4 and the JPEG / OpenJPEG / ffi
# shared libs at runtime — Cairo is no longer required since WeasyPrint v52.5.
# These libs ship in the Debian "trixie-slim" base, so no PPA is needed.
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libjpeg-dev \
    libopenjp2-7-dev \
    libffi-dev \
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

### Stage 5: Download pre-built binaries for OSV-Scanner and Cosign
FROM alpine:3.21 AS binary-downloader
ARG OSV_SCANNER_VERSION
ARG COSIGN_VERSION
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

# Install debug tools (only needed in development, not in production)
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

# Set environment variables — PATH must include .venv/bin so bare `python` commands
# (used by worker and migrations services) find Django and other dependencies.
ENV PATH="/code/.venv/bin:${PATH}" \
    PROMETHEUS_MULTIPROC_DIR=/var/lib/dramatiq-prometheus \
    UV_CACHE_DIR=/tmp/.cache/uv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp

# Switch to non-root user
USER nobody

EXPOSE 8000
# CMD for Development (using uvicorn directly with reload for development)
CMD ["uv", "run", "uvicorn", "sbomify.asgi:application", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-include", "*.j2", "--log-level", "info"]
### Stage 7a: Collect static files and prepare for distroless (runs on Debian)
# This stage runs on Debian where uv, Django, and shell utilities are available.
# All file operations (collectstatic, symlink fixing, lib staging, dir creation)
# must happen here because the distroless prod image has NO shell at all.
FROM python-dependencies AS collectstatic

WORKDIR /code

# Copy built frontend assets
COPY --from=js-build-prod /js-build/sbomify/static/dist /code/sbomify/static/dist
COPY --from=js-build-prod /js-build/sbomify/static/css /code/sbomify/static/css
COPY --from=js-build-prod /js-build/sbomify/static/webfonts /code/sbomify/static/webfonts
# Copy the compiled Keycloak theme CSS from the separate Keycloak build stage
COPY --from=keycloak-build /keycloak-build/themes/sbomify/login/resources/css /code/keycloak/themes/sbomify/login/resources/css

# Prevent uv run from implicitly syncing (which would reinstall dev dependencies)
ENV UV_NO_SYNC=1

# Run collectstatic, fix Python symlinks for Chainguard, and prepare runtime directories.
# Chainguard Python is at /usr/bin/python, not /usr/local/bin/python3.X.
# The python3.X symlink name is derived dynamically to avoid hardcoding the minor version.
# psycopg2-binary bundles libpq, so no shared library staging is needed.
#
# Strip test_data/ fixtures from the prod tree before it is copied into the
# distroless image. They are sample SBOMs/lockfiles used only by the test suite;
# `COPY . .` bakes them in, where the image SBOM scanner reads them as installed
# packages and reports phantom CVEs for the historical snapshots they describe.
# This runs ONLY in the collectstatic -> python-app-prod path, so the dev image
# (python-app-dev, built from python-dependencies) keeps the fixtures that the
# create_test_sbom_environment management command loads.
RUN mkdir -p /code/staticfiles && \
    uv run python manage.py collectstatic --noinput && \
    PYTHON_MINOR=$(python3 -c 'import sys; print("python%d.%d" % sys.version_info[:2])') && \
    rm -f /code/.venv/bin/python /code/.venv/bin/python3 "/code/.venv/bin/${PYTHON_MINOR}" && \
    ln -s /usr/bin/python /code/.venv/bin/python && \
    ln -s /usr/bin/python /code/.venv/bin/python3 && \
    ln -s /usr/bin/python "/code/.venv/bin/${PYTHON_MINOR}" && \
    find /code/sbomify -type d -name test_data -prune -exec rm -rf {} + && \
    mkdir -p /staged-dirs/var/lib/dramatiq-prometheus /staged-dirs/tmp/.cache && \
    chown -R 65532:65532 /staged-dirs/var /staged-dirs/tmp

### Stage 7b: Stage WeasyPrint runtime libraries from Wolfi
# WeasyPrint dlopen()s Pango / HarfBuzz / OpenJPEG / libjpeg / FreeType /
# fontconfig / glib at write_pdf() time, NOT at import time. The Chainguard
# distroless prod image (Stage 7) does not ship these libs, so PDF rendering
# fails at runtime with "PDF rendering is unavailable" even though the
# WeasyPrint Python package itself imports cleanly. We install the libs in
# a Wolfi-based builder stage and COPY them into the distroless image.
#
# Wolfi-base shares the same glibc as cgr.dev/chainguard/python (both are
# built on Wolfi-glibc), so .so files copied across stages are ABI-safe —
# unlike copying libs from a Debian builder, which would risk glibc skew.
# Fonts (font-liberation + fontconfig) are required because WeasyPrint
# asks fontconfig for fallbacks at render time; without a font, text
# glyphs render as boxes instead of the chosen Helvetica/Arial fallback.
ARG CHAINGUARD_WOLFI_BASE_IMAGE
FROM ${CHAINGUARD_WOLFI_BASE_IMAGE} AS weasyprint-libs
# font-liberation is a metric-compatible drop-in for Arial / Helvetica /
# Times New Roman / Courier (the families the print CSS targets) at
# ~3 MB. font-noto's full multi-script set is ~470 MB — needlessly
# bloats the prod image since the DoC is Latin / Latin-extended /
# Cyrillic / Greek only and Liberation covers all four.
RUN apk add --no-cache \
        pango \
        harfbuzz \
        openjpeg \
        libjpeg-turbo \
        fontconfig \
        freetype \
        glib \
        font-liberation

# Stage just the .so files WeasyPrint actually dlopen()s plus their transitive
# deps (verified with ld-linux --list against libpango / libpangoft2 / libharfbuzz
# / libfreetype / libfontconfig / libopenjp2 / libjpeg) and the Liberation Sans
# weights + Liberation Mono Regular the print CSS targets. Copying these
# specific files instead of /usr/lib + /usr/share/fonts wholesale shrinks the
# runtime payload from ~46 MB to ~18 MB. libc / libm / libffi / ld-linux are
# already in the prod image — re-copying them would risk a glibc skew, so
# they're intentionally omitted.
#
# Font selection: Liberation Sans is the metric-compatible Arial / Helvetica
# substitute (the families the body CSS asks for) — fontconfig resolves the
# CSS request to it. The 4 .ttf files shipped (LiberationSans Regular + Bold
# + Italic, plus LiberationMono Regular) were picked by auditing the actual
# HTML the markdown renderer produces against every CRA document kind:
#   - body text: present everywhere → ship Sans Regular.
#   - <strong> tags: present in all 4 docs (3-19 each) → ship Sans Bold.
#   - <em> tags: present in all 4 docs (1-18 each) → ship Sans Italic.
#   - <strong><em> nested: 0 across all docs → SansBoldItalic skipped;
#     fontconfig synthesizes acceptable bold-italic from Italic / Bold if a
#     future template introduces ***foo***.
#   - <code> tags: present only in the DoC (10 each), never bolded or
#     italicized → ship LiberationMono-Regular only.
# Skipped weights: LiberationSans-BoldItalic, all 4 LiberationSerif weights,
# and LiberationMono Bold / Italic / BoldItalic.
# fontconfig setup (/etc/fonts + /usr/share/fontconfig) ships verbatim
# because the per-family conf snippets are small (~370 KB combined) and
# trimming them would require auditing every snippet.
RUN mkdir -p /staged/usr/lib /staged/usr/share/fonts/font-liberation \
             /staged/usr/share/fontconfig /staged/etc/fonts && \
    cd /usr/lib && cp -a \
        libpango-1.0.so* libpangoft2-1.0.so* \
        libharfbuzz.so* \
        libfreetype.so* \
        libfontconfig.so* \
        libopenjp2.so* libjpeg.so* \
        libbrotlicommon.so* libbrotlidec.so* \
        libbz2.so* libexpat.so* libfribidi.so* libgraphite2.so* \
        libgio-2.0.so* libglib-2.0.so* libgmodule-2.0.so* libgobject-2.0.so* \
        libpcre2-8.so* libpng16.so* libz.so* \
        libblkid.so* libmount.so* libselinux.so* \
        /staged/usr/lib/ && \
    cp -a /usr/share/fonts/font-liberation/LiberationSans-Regular.ttf \
          /usr/share/fonts/font-liberation/LiberationSans-Bold.ttf \
          /usr/share/fonts/font-liberation/LiberationSans-Italic.ttf \
          /usr/share/fonts/font-liberation/LiberationMono-Regular.ttf \
          /staged/usr/share/fonts/font-liberation/ && \
    cp -a /usr/share/fontconfig/. /staged/usr/share/fontconfig/ && \
    cp -a /etc/fonts/. /staged/etc/fonts/

### Stage 7: Python Application for Production (python-app-prod)
# Uses Chainguard distroless Python — no shell, no apt, no pip, no uv at runtime.
# This reduces CVEs significantly and shrinks the image by ~50%.
# IMPORTANT: No RUN commands are possible here (no /bin/sh in distroless).
ARG CHAINGUARD_PYTHON_IMAGE
FROM ${CHAINGUARD_PYTHON_IMAGE} AS python-app-prod

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

# Clear Chainguard's ENTRYPOINT ["/usr/bin/python"] so CMD and docker-compose
# commands resolve via PATH instead of being passed as arguments to python.
ENTRYPOINT []

# Copy application code, .venv (with fixed symlinks), and collected static files
COPY --from=collectstatic /code /code

# Copy the osv-scanner and cosign binaries from the binary-downloader stage
COPY --from=binary-downloader /usr/local/bin/osv-scanner /usr/local/bin/osv-scanner
COPY --from=binary-downloader /usr/local/bin/cosign /usr/local/bin/cosign

# Copy the slimmed /staged tree (pre-filtered to WeasyPrint's actual .so
# closure plus the Liberation Sans / Mono fonts the print CSS references).
COPY --from=weasyprint-libs /staged/ /

# Copy pre-created runtime directories with nonroot ownership (UID 65532)
COPY --from=collectstatic /staged-dirs/var/lib/dramatiq-prometheus /var/lib/dramatiq-prometheus
COPY --from=collectstatic --chown=65532:65532 /staged-dirs/tmp/ /tmp/

# Set environment variables for Prometheus metrics and build metadata
# No UV_CACHE_DIR or UV_NO_SYNC needed — uv is not present in distroless
ENV PATH="/code/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROMETHEUS_MULTIPROC_DIR=/var/lib/dramatiq-prometheus \
    HOME=/tmp \
    SBOMIFY_BUILD_DATE="${BUILD_DATE}" \
    SBOMIFY_GIT_COMMIT="${GIT_COMMIT}" \
    SBOMIFY_GIT_COMMIT_SHORT="${GIT_COMMIT_SHORT}" \
    SBOMIFY_GIT_REF="${GIT_REF}" \
    SBOMIFY_VERSION="${VERSION}" \
    SBOMIFY_BUILD_TYPE="${BUILD_TYPE}"

# Switch to non-root user (Chainguard's built-in nonroot user, UID 65532)
USER nonroot

EXPOSE 8000
# CMD for Production - Run gunicorn directly from .venv (no uv, no shell needed)
# --graceful-timeout 30: Workers get 30s to finish requests on SIGTERM
# --timeout 120: Max time for a single request (2 min for large SBOM uploads)
CMD ["gunicorn", "sbomify.asgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--worker-class", "uvicorn_worker.UvicornWorker", \
     "--graceful-timeout", "30", \
     "--timeout", "120"]

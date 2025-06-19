# Base Python version
ARG PYTHON_VERSION=3.12-slim-bookworm
ARG BUILD_ENV=production # Default to production
ARG OSV_SCANNER_VERSION=v2.0.2
ARG CYCLONEDX_GOMOD_VERSION=v1.9.0

### Stage 1: Bun JS build for Production Frontend Assets
FROM oven/bun:1.2-debian AS js-build-prod

WORKDIR /js-build

# Copy all frontend configuration files first
COPY package.json ./
COPY bun.lock ./
COPY tsconfig*.json ./
COPY vite.config.ts ./
COPY eslint.config.js ./
COPY .prettierrc.js ./

# Install dependencies
RUN bun install --frozen-lockfile

# Copy source files
COPY core/js/ ./core/js/
COPY sboms/js/ ./sboms/js/
COPY teams/js/ ./teams/js/
COPY billing/js/ ./billing/js/

# Run the build for production - assumes output is to 'staticfiles' directory
RUN bun run build

### Stage 2: Frontend Development Server
FROM oven/bun:1.2-debian AS frontend-dev-server

WORKDIR /app-frontend

# Copy frontend configuration and source
COPY package.json ./
COPY bun.lock ./
COPY tsconfig*.json ./
COPY vite.config.ts ./
COPY eslint.config.js ./
COPY .prettierrc.js ./
COPY core/js/ ./core/js/
COPY sboms/js/ ./sboms/js/
COPY teams/js/ ./teams/js/
COPY billing/js/ ./billing/js/

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
FROM golang:1.24-alpine AS go-builder
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

EXPOSE 8000
# CMD for Development (using Django's runserver)
CMD ["poetry", "run", "python", "manage.py", "runserver", "0.0.0.0:8000"]

### Stage 7: Python Application for Production (python-app-prod)
# This is the default final stage if no target is specified.
FROM python-dependencies AS python-app-prod

WORKDIR /code

# Copy the osv-scanner binary from the go-builder stage
COPY --from=go-builder /go/bin/osv-scanner /usr/local/bin/osv-scanner

# Production-specific steps
COPY --from=js-build-prod /js-build/staticfiles/* /code/staticfiles/
RUN poetry run python manage.py collectstatic --noinput

EXPOSE 8000
# CMD for Production
CMD ["poetry", "run", "gunicorn", "--bind", ":8000", "--workers", "2", "sbomify.wsgi"]

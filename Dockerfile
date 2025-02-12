ARG PYTHON_VERSION=3.11-slim-bookworm

### Bun JS build for Vue components
FROM oven/bun:1.2.2 AS js-build

WORKDIR /js-build

# Copy all frontend configuration files first
COPY package.json ./
COPY bun.lock ./
COPY tsconfig*.json ./
COPY vite.config.ts ./
COPY eslint.config.js ./
COPY .prettierrc.js ./

# Clean install dependencies
RUN bun install --frozen-lockfile

# Copy source files
COPY core/js/ core/js/
COPY sboms/js/ sboms/js/
COPY teams/js/ teams/js/
COPY billing/js/ billing/js/

# Run the build
RUN bun run build

## Python App Build
FROM python:${PYTHON_VERSION}

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# install psycopg2 dependencies.
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /code
WORKDIR /code

# Install Python dependencies
RUN pip install poetry
COPY pyproject.toml poetry.lock /code/
RUN poetry config virtualenvs.create false

# Install only main and prod dependencies
RUN poetry install --only main,prod --no-interaction --no-root

# Copy application code
COPY . /code

# Copy built JS assets to static directory
COPY --from=js-build /js-build/static/* /code/static/

# Install the package itself
RUN poetry install --only-root --no-interaction

# Collect static files
RUN poetry run python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["poetry", "run", "gunicorn", "--bind", ":8000", "--workers", "2", "sbomify.wsgi"]

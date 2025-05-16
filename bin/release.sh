#!/usr/bin/env sh

set -e  # Exit on any error

echo "Starting migration process..."

# Run migrations in the correct order
echo "Running migrations..."
if ! poetry run python manage.py migrate --noinput; then
    echo "Failed to run migrations"
    exit 1
fi

echo "Migration process completed successfully"
#!/usr/bin/env sh

set -e  # Exit on any error

echo "Starting migration process..."

# Fix migration history first
echo "Fixing migration history..."
if ! poetry run python manage.py fix_migrations; then
    echo "Failed to fix migration history"
    exit 1
fi

# Run migrations in the correct order
echo "Running migrations..."
if ! poetry run python manage.py migrate --noinput; then
    echo "Failed to run migrations"
    exit 1
fi

echo "Migration process completed successfully"
#!/usr/bin/env sh

set -e  # Exit on any error

echo "Starting migration process..."

# Check if django_migrations table exists and has any records
if echo "SELECT EXISTS (SELECT 1 FROM django_migrations LIMIT 1);" | poetry run python manage.py dbshell | grep -q "t"; then
    echo "Existing database detected, fixing migration history..."
    if ! poetry run python manage.py fix_migrations; then
        echo "Failed to fix migration history"
        exit 1
    fi
else
    echo "Clean database detected, running initial migrations..."
fi

# Run migrations in the correct order
echo "Running migrations..."
if ! poetry run python manage.py migrate --noinput; then
    echo "Failed to run migrations"
    exit 1
fi

echo "Migration process completed successfully"
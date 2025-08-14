#!/usr/bin/env sh

set -e  # Exit on any error

echo "Starting release process..."

# Step 1: Run migrations
echo "Running migrations..."
if ! poetry run python manage.py migrate --noinput; then
    echo "Failed to run migrations"
    exit 1
fi

# Step 2: Clear Redis cache
echo "Clearing Redis cache..."
if ! poetry run python manage.py shell -c "
from django.core.cache import cache
try:
    cache.clear()
    print('✓ Redis cache cleared successfully')
except Exception as e:
    print(f'⚠ Warning: Could not clear Redis cache: {e}')
    # Don't fail the deployment for cache clearing issues
"; then
    echo "⚠ Warning: Redis cache clearing failed, continuing deployment..."
fi

echo "Release process completed successfully"
#!/usr/bin/env sh

# Fix migration history
poetry run python manage.py fix_migrations

# Run all migrations
poetry run python manage.py migrate --noinput
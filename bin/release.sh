#!/usr/bin/env sh

# First run sites migration
poetry run python manage.py migrate sites --noinput

# Then run all other migrations
poetry run python manage.py migrate --noinput
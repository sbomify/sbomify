# Changelog - v0.18.0

Release Date: October 31, 2024

## Major Changes

- **Migrated from Poetry to UV** for faster Python dependency management (#362)
- **Migrated from Vue.js to HTMX** for Dashboard, Components, Products, Projects, and Releases pages
- **Migrated from Gunicorn to Uvicorn** with ASGI lifespan protocol support (#255, #366)
- **Restructured Django apps** to `sbomify/apps/` directory (#274)
- **Security enhancement**: Docker containers now run as non-root user (#280)

## Features

- Added comprehensive user onboarding system with email notifications (#311, #312)
- Added promo code support for Stripe checkout (#313)
- Enhanced admin interface with improved model configurations (#314)
- Fixed email availability for username/password signups (#346)

## Bug Fixes

- Fixed trial subscription creation errors for OIDC users (#302, #304, #305)
- Fixed Redis settings and database configuration issues (#335)
- Fixed onboarding email task registration (#328, #330, #331)
- Fixed attestation permission errors in GitHub Actions (#256, #257)
- Made developer mode podman/docker agnostic (#330)

## Technical Improvements

- Replaced function-based views with class-based views
- Improved template structure and CSS organization
- Enhanced pagination and API logic
- Updated CI/CD workflows and permissions

## Migration Notes

If upgrading from v0.17.2:

1. Use `uv run` instead of `poetry run` for Python commands
2. Major UI pages migrated from Vue.js to HTMX
3. ASGI server is now Uvicorn instead of Gunicorn
4. Django apps moved to `sbomify/apps/` directory
5. Docker containers run as non-root user

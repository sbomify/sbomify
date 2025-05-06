# Release Process

This document outlines the steps to cut a new release of sbomify.

## Steps

1. Run pre-release checks:

```bash
# Run linting
poetry run ruff check .
poetry run ruff format --check .
bun markdownlint "**/*.md" --ignore node_modules

# Run tests and coverage
poetry run coverage run -m pytest
poetry run coverage report
```

Ensure all tests pass, coverage is at least 80%, and there are no linting errors.

1. Bump the version in `pyproject.toml` using Poetry:

```bash
poetry version patch  # For patch version (0.0.x)
# OR
poetry version minor  # For minor version (0.x.0)
# OR
poetry version major  # For major version (x.0.0)
```

1. Get the new version number:

```bash
poetry version --short
```

1. Create and push a new git tag:

```bash
# Replace X.Y.Z with the version from step 2
git tag -a vX.Y.Z -m "Release version X.Y.Z"
git push origin vX.Y.Z
```

## Example

For a patch release from 0.2.0 to 0.2.1:

```bash
# Run pre-release checks
poetry run ruff check .
poetry run ruff format --check .
bun markdownlint "**/*.md"
poetry run coverage run -m pytest
poetry run coverage report

# Bump version
poetry version patch
# Version bumped to 0.2.1

# Create and push tag
git tag -a v0.2.1 -m "Release version 0.2.1"
git push origin v0.2.1
```

## Notes

- Always ensure all tests pass before cutting a release
- Update the changelog if one exists
- Consider creating a GitHub release with release notes

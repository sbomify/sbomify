# Release Process

This document outlines the steps to cut a new release of sbomify.

## Steps

1. Run pre-release checks:

```bash
# Run linting
uv run ruff check .
uv run ruff format --check .
bun markdownlint "**/*.md" --ignore node_modules

# Run tests and coverage
uv run coverage run -m pytest
uv run coverage report
```

Ensure all tests pass, coverage is at least 80%, and there are no linting errors.

1. Bump the version in `pyproject.toml` manually by editing the version field.

1. Get the new version number:

```bash
grep '^version = ' pyproject.toml | cut -d'"' -f2
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
uv run ruff check .
uv run ruff format --check .
bun markdownlint "**/*.md"
uv run coverage run -m pytest
uv run coverage report

# Bump version (edit pyproject.toml manually)
# Change version = "0.2.0" to version = "0.2.1"

# Get version for tag
VERSION=$(grep '^version = ' pyproject.toml | cut -d'"' -f2)

# Create and push tag
git tag -a v${VERSION} -m "Release version ${VERSION}"
git push origin v${VERSION}
```

## Notes

- Always ensure all tests pass before cutting a release
- Update the changelog if one exists
- Consider creating a GitHub release with release notes

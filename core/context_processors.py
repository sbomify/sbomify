from importlib.metadata import PackageNotFoundError, version


def version_context(request):
    """Add version information to template context."""
    try:
        app_version = version("sbomify")
    except PackageNotFoundError:
        app_version = "0.13.0"  # Fallback to current version from pyproject.toml

    return {"app_version": app_version}

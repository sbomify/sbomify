from importlib.metadata import PackageNotFoundError, version


def version_context(request):
    """Add version information to template context."""
    try:
        app_version = version("sbomify")
    except PackageNotFoundError:
        app_version = None  # Don't show version if package not found

    return {"app_version": app_version}

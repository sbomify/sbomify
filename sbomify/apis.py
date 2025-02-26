from importlib.metadata import PackageNotFoundError, version

from ninja import NinjaAPI

try:
    __version__ = version("sbomify")
except PackageNotFoundError:
    __version__ = "0.2.0"  # Fallback to current version

api = NinjaAPI(
    title="sbomify API",
    version=__version__,
    description="API for managing Software Bill of Materials (SBOM)",
    openapi_url="/openapi.json",
    docs_url="/docs",
    urls_namespace="api-1"
)

api.add_router("/sboms", "sboms.apis.router")
api.add_router("/teams", "teams.apis.router")
api.add_router("/", "core.apis.router")
api.add_router("/billing", "billing.apis.router")
api.add_router("/notifications", "notifications.apis.router")

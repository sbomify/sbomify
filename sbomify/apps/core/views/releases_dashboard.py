"""Existing release URLs open the shared Products inventory."""

from sbomify.apps.core.views.products_dashboard import InventoryView, ProductsTableView


class ReleasesDashboardView(InventoryView):
    inventory_kind = "releases"


class ReleasesTableView(ProductsTableView):
    inventory_kind = "releases"

"""Existing release URLs open the shared Products inventory."""

from sbomify.apps.core.views.products_dashboard import InventoryView


class ReleasesDashboardView(InventoryView):
    inventory_kind = "releases"

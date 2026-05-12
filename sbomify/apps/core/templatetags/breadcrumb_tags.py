from __future__ import annotations

from typing import Any

from django import template
from django.urls import reverse

from sbomify.apps.core.models import Product

register = template.Library()


def _get_trust_center_crumb(context: Any) -> Any:
    """Get the Trust Center (workspace) breadcrumb if available.

    Returns None if Trust Center is not enabled (no workspace_public_url).
    """
    workspace_public_url = context.get("workspace_public_url")
    brand = context.get("brand", {})
    if workspace_public_url:
        brand_name = brand.get("name") if isinstance(brand, dict) else getattr(brand, "name", None)
        return {
            "name": f"{brand_name} Trust Center" if brand_name else "Trust Center",
            "url": workspace_public_url,
            "icon": "fas fa-shield-alt",
        }
    return None


@register.inclusion_tag("core/components/breadcrumb.html.j2", takes_context=True)
def breadcrumb(context: Any, item: Any, item_type: Any) -> Any:
    """Generate breadcrumb navigation for public pages.

    Args:
        context: Template context (includes request)
        item: The current item (Product, Component, or Release)
        item_type: String indicating the type ('product', 'component', 'release', 'releases')

    Returns:
        Context dictionary for the breadcrumb template

    Note: Components attach directly to products under the post-#946
    ``Product → Component`` model; the legacy Project layer is gone.
    Components link back to their parent product(s) only.
    """
    crumbs = []
    request = context.get("request")

    # Add Trust Center as root for all pages
    trust_center_crumb = _get_trust_center_crumb(context)
    if trust_center_crumb:
        crumbs.append(trust_center_crumb)

    def detect_product_from_referrer(public_products: Any) -> Any:
        """Try to detect which product the user navigated from based on referrer."""
        if not request or not hasattr(request, "META"):
            return None

        referrer = request.META.get("HTTP_REFERER", "")
        if not referrer:
            return None

        # Extract ID from referrer URL patterns like /public/product/ID/ or /product/SLUG/
        import re

        # Try standard URL pattern
        pattern = r"/public/product/([^/]+)/"
        match = re.search(pattern, referrer)
        if match:
            product_id = match.group(1)
            for product in public_products:
                if str(product.id) == product_id:
                    return product

        # Try custom domain URL pattern
        pattern = r"/product/([^/]+)/"
        match = re.search(pattern, referrer)
        if match:
            slug_or_id = match.group(1)
            for product in public_products:
                if str(product.id) == slug_or_id or product.slug == slug_or_id:
                    return product

        return None

    # Handle release and releases types - show parent product
    if item_type in ("release", "releases"):
        product = context.get("product")
        if not product and hasattr(item, "product"):
            product = item.product
        if product:
            # Handle both dict and model object
            if isinstance(product, dict):
                product_name = product.get("name")
                product_id = product.get("id")
            else:
                product_name = product.name
                product_id = product.id

            if product_name and product_id:
                crumbs.append(
                    {
                        "name": product_name,
                        "url": reverse("core:product_details_public", kwargs={"product_id": product_id}),
                        "icon": "fas fa-box",
                    }
                )
        return {"crumbs": crumbs}

    elif item_type == "component":
        component_id = item.get("id") if isinstance(item, dict) else item.id
        # Limit columns + cap to a small set; the referrer-match loop only
        # needs `id`, `name`, and `Product.slug`, and there's no value in
        # materialising every public product attached to a heavily-shared
        # component.
        #
        # `Product.slug` is a `@property` computed from `name` via
        # `slugify()` (see sboms/models.py), not a deferred DB column —
        # so `.only("id", "name")` covers `detect_product_from_referrer`'s
        # access pattern (`product.id`, `product.name`, `product.slug`)
        # without triggering an N+1.
        public_products = (
            Product.objects.filter(components__id=component_id, is_public=True)
            .order_by("id")
            .only("id", "name")
            .distinct()[:25]
        )

        if public_products:
            product = detect_product_from_referrer(public_products)
            if not product:
                product = public_products[0]

            crumbs.append(
                {
                    "name": product.name,
                    "url": reverse("core:product_details_public", kwargs={"product_id": product.id}),
                    "icon": "fas fa-box",
                }
            )

    # For products, only the Trust Center crumb is shown (products are direct children of Trust Center)
    return {"crumbs": crumbs}


@register.simple_tag
def get_breadcrumb_data(item: Any, item_type: Any) -> Any:
    """Get breadcrumb data as a dictionary for JavaScript use."""
    crumbs = []

    if item_type == "component":
        component_id = item.get("id") if isinstance(item, dict) else item.id
        public_products = Product.objects.filter(components__id=component_id, is_public=True).order_by("id").distinct()
        # Walrus narrows the type for mypy without an `# type: ignore`.
        if product := public_products.first():
            crumbs.append(
                {
                    "name": product.name,
                    "url": reverse("core:product_details_public", kwargs={"product_id": product.id}),
                    "type": "product",
                }
            )

    return crumbs

from django import template
from django.urls import reverse

from sbomify.apps.core.models import Product, Project

register = template.Library()


def _get_trust_center_crumb(context):
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
def breadcrumb(context, item, item_type):
    """Generate breadcrumb navigation for public pages.

    Args:
        context: Template context (includes request)
        item: The current item (Product, Component, or Release)
        item_type: String indicating the type ('product', 'component', 'release', 'releases')

    Returns:
        Context dictionary for the breadcrumb template

    Note: Projects no longer have standalone public pages - they are integrated
    into product pages. Components link back to their parent product.
    """
    crumbs = []
    request = context.get("request")

    # Add Trust Center as root for all pages
    trust_center_crumb = _get_trust_center_crumb(context)
    if trust_center_crumb:
        crumbs.append(trust_center_crumb)

    def detect_product_from_referrer(public_products):
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
        # For components, show the parent product (via project)
        if isinstance(item, dict):
            public_projects = Project.objects.filter(component__id=item.get("id"), is_public=True)
        else:
            public_projects = item.projects.filter(is_public=True)

        if public_projects.exists():
            # Collect ALL public products across all public projects
            public_products = (
                Product.objects.filter(projects__in=public_projects, is_public=True).order_by("id").distinct("id")
            )

            if public_products.exists():
                product = detect_product_from_referrer(public_products)
                if not product:
                    product = public_products.first()

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
def get_breadcrumb_data(item, item_type):
    """Get breadcrumb data as a dictionary for JavaScript use."""
    crumbs = []

    if item_type == "component":
        if isinstance(item, dict):
            public_projects = Project.objects.filter(component__id=item.get("id"), is_public=True)
        else:
            public_projects = item.projects.filter(is_public=True)

        if public_projects.exists():
            # Collect ALL public products across all public projects
            public_products = (
                Product.objects.filter(projects__in=public_projects, is_public=True).order_by("id").distinct("id")
            )
            if public_products.exists():
                product = public_products.first()
                crumbs.append(
                    {
                        "name": product.name,
                        "url": reverse("core:product_details_public", kwargs={"product_id": product.id}),
                        "type": "product",
                    }
                )

    return crumbs

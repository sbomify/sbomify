from django import template
from django.urls import reverse

from sbomify.apps.core.models import Product, Project

register = template.Library()


@register.inclusion_tag("core/components/breadcrumb.html.j2", takes_context=True)
def breadcrumb(context, item, item_type, detailed=False):
    """Generate breadcrumb navigation for public pages.

    Args:
        context: Template context (includes request)
        item: The current item (Product, Project, or Component)
        item_type: String indicating the type ('product', 'project', 'component')
        detailed: Boolean indicating if this is a detailed view

    Returns:
        Context dictionary for the breadcrumb template
    """
    crumbs = []
    request = context.get("request")

    def detect_parent_from_referrer(public_parents, parent_type):
        """Try to detect which parent the user navigated from based on referrer."""
        if not request or not hasattr(request, "META"):
            return None

        referrer = request.META.get("HTTP_REFERER", "")
        if not referrer:
            return None

        # Extract ID from referrer URL patterns like /public/project/ID/ or /public/product/ID/
        import re

        pattern = rf"/public/{parent_type}/([^/]+)/"
        match = re.search(pattern, referrer)
        if match:
            parent_id = match.group(1)
            # Find the parent with this ID
            for parent in public_parents:
                if str(parent.id) == parent_id:
                    return parent
        return None

    if item_type == "project":
        # For projects, show parent products (if any are public)
        if isinstance(item, dict):
            public_products = Product.objects.filter(project__id=item.get("id"), is_public=True)
        else:
            public_products = item.products.filter(is_public=True)

        if public_products.exists():
            # Try to detect which product the user came from
            product = detect_parent_from_referrer(public_products, "product")
            if not product:
                # If multiple products and we can't detect, show the first one
                # TODO: Could show multiple paths or let user choose
                product = public_products.first()

            crumbs.append(
                {
                    "name": product.name,
                    "url": reverse("core:product_details_public", kwargs={"product_id": product.id}),
                    "icon": "fas fa-box",
                }
            )

    elif item_type == "component":
        # For components, show a simple hierarchy: Product > Project > Component
        if isinstance(item, dict):
            public_projects = Project.objects.filter(component__id=item.get("id"), is_public=True)
        else:
            public_projects = item.projects.filter(is_public=True)

        if public_projects.exists():
            # Try to detect which project the user came from, otherwise use first
            project = detect_parent_from_referrer(public_projects, "project")
            if not project:
                project = public_projects.first()

            # Check if this project has public products
            public_products = project.products.filter(is_public=True)
            if public_products.exists():
                # Try to detect which product the user might have come from, otherwise use first
                product = detect_parent_from_referrer(public_products, "product")
                if not product:
                    product = public_products.first()

                crumbs.append(
                    {
                        "name": product.name,
                        "url": reverse("core:product_details_public", kwargs={"product_id": product.id}),
                        "icon": "fas fa-box",
                    }
                )

            # Add the primary project
            crumbs.append(
                {
                    "name": project.name,
                    "url": reverse("core:project_details_public", kwargs={"project_id": project.id}),
                    "icon": "fas fa-project-diagram",
                }
            )

    # Don't add the current item to breadcrumbs since it's redundant with the page header
    return {"crumbs": crumbs}


@register.simple_tag
def get_breadcrumb_data(item, item_type):
    """Get breadcrumb data as a dictionary for JavaScript use."""
    crumbs = []

    if item_type == "project":
        if isinstance(item, dict):
            public_products = Product.objects.filter(project__id=item.get("id"), is_public=True)
        else:
            public_products = item.products.filter(is_public=True)

        if public_products.exists():
            product = public_products.first()
            crumbs.append(
                {
                    "name": product.name,
                    "url": reverse("core:product_details_public", kwargs={"product_id": product.id}),
                    "type": "product",
                }
            )

    elif item_type == "component":
        if isinstance(item, dict):
            public_projects = Project.objects.filter(component__id=item.get("id"), is_public=True)
        else:
            public_projects = item.projects.filter(is_public=True)

        if public_projects.exists():
            project = public_projects.first()

            public_products = project.products.filter(is_public=True)
            if public_products.exists():
                product = public_products.first()
                crumbs.append(
                    {
                        "name": product.name,
                        "url": reverse("core:product_details_public", kwargs={"product_id": product.id}),
                        "type": "product",
                    }
                )

            crumbs.append(
                {
                    "name": project.name,
                    "url": reverse("core:project_details_public", kwargs={"project_id": project.id}),
                    "type": "project",
                }
            )

    return crumbs

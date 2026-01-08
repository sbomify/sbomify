from django.db.models import Count, Exists, OuterRef
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.core.apis import get_product
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Release, ReleaseArtifact
from sbomify.apps.core.url_utils import (
    add_custom_domain_to_context,
    build_custom_domain_url,
    get_public_path,
    resolve_product_identifier,
    should_redirect_to_clean_url,
    should_redirect_to_custom_domain,
)
from sbomify.apps.plugins.public_assessment_utils import (
    get_product_assessment_status,
    passing_assessments_to_dict,
)
from sbomify.apps.sboms.models import SBOM, ProductIdentifier, ProductLink
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team


def _prepare_public_projects(projects: list, is_custom_domain: bool) -> list:
    """Prepare project data with public URLs, filtering to only public projects."""
    public_projects = []
    for project in projects:
        if not project.get("is_public"):
            continue
        project_data = {
            "id": project["id"],
            "name": project["name"],
            "slug": project.get("slug"),
            "is_public": True,
        }
        # Build public URL based on domain type
        if is_custom_domain:
            project_data["public_url"] = f"/project/{project.get('slug') or project['id']}/"
        else:
            project_data["public_url"] = f"/public/project/{project['id']}/"
        public_projects.append(project_data)
    return public_projects


def _get_public_releases(product_id: str, is_custom_domain: bool, product_slug: str, limit: int = 5) -> list:
    """Get releases for a public product (releases inherit visibility from their product)."""
    # Use annotations to avoid N+1 queries for artifacts_count and has_sboms
    releases = (
        Release.objects.filter(product_id=product_id)
        .select_related("product")
        .annotate(
            annotated_artifacts_count=Count("artifacts"),
            annotated_has_sboms=Exists(ReleaseArtifact.objects.filter(release=OuterRef("pk"), sbom__isnull=False)),
        )
        .order_by("-released_at", "-created_at")[:limit]
    )

    public_releases = []
    for release in releases:
        release_data = {
            "id": release.id,
            "name": release.name,
            "slug": getattr(release, "slug", None),
            "description": release.description,
            "is_latest": release.is_latest,
            "is_prerelease": release.is_prerelease,
            "created_at": release.created_at,
            "released_at": release.released_at,
            "artifacts_count": release.annotated_artifacts_count,
            "has_sboms": release.annotated_has_sboms,
        }
        if is_custom_domain:
            release_data["public_url"] = f"/product/{product_slug}/release/{release_data['slug'] or release.id}/"
        else:
            release_data["public_url"] = f"/public/product/{product_id}/release/{release.id}/"
        public_releases.append(release_data)
    return public_releases


def _get_product_identifiers(product_id: str) -> list:
    """Get product identifiers."""
    identifiers = ProductIdentifier.objects.filter(product_id=product_id).order_by("identifier_type")
    return [
        {
            "id": identifier.id,
            "identifier_type": identifier.identifier_type,
            "identifier_type_display": identifier.get_identifier_type_display(),
            "value": identifier.value,
        }
        for identifier in identifiers
    ]


def _get_product_links(product_id: str) -> list:
    """Get product links."""
    links = ProductLink.objects.filter(product_id=product_id).order_by("link_type")
    return [
        {
            "id": link.id,
            "link_type": link.link_type,
            "link_type_display": link.get_link_type_display(),
            "title": link.title,
            "url": link.url,
            "description": link.description,
        }
        for link in links
    ]


class ProductDetailsPublicView(View):
    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        # Resolve product by slug (on custom domains) or ID (on main app)
        product_obj = resolve_product_identifier(request, product_id)
        if not product_obj:
            return error_response(request, HttpResponseNotFound("Product not found"))

        # Use the resolved product's ID for API calls
        resolved_id = product_obj.id

        status_code, product = get_product(request, resolved_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=product.get("detail", "Unknown error"))
            )

        has_downloadable_content = SBOM.objects.filter(component__projects__products__id=resolved_id).exists()
        team = Team.objects.filter(pk=product.get("team_id")).first()

        # Redirect to custom domain if team has a verified one and we're not already on it
        # OR redirect from /public/ URL to clean URL on custom domain
        if team and (should_redirect_to_custom_domain(request, team) or should_redirect_to_clean_url(request)):
            path = get_public_path("product", resolved_id, is_custom_domain=True, slug=product_obj.slug)
            return HttpResponseRedirect(build_custom_domain_url(team, path, request.is_secure()))

        brand = build_branding_context(team)
        is_custom_domain = getattr(request, "is_custom_domain", False)

        # Prepare server-side data for Django templates (replacing Vue components)
        public_projects = _prepare_public_projects(product.get("projects", []), is_custom_domain)
        public_releases = _get_public_releases(resolved_id, is_custom_domain, product.get("slug") or resolved_id)
        product_identifiers = _get_product_identifiers(resolved_id)
        product_links = _get_product_links(resolved_id)

        # Build view all releases URL
        if is_custom_domain:
            view_all_releases_url = f"/product/{product.get('slug') or resolved_id}/releases/"
        else:
            view_all_releases_url = reverse(
                "core:product_releases_public",
                kwargs={"product_id": resolved_id},
            )

        # Get aggregated assessment status for this product (only passing assessments)
        assessment_status = get_product_assessment_status(product_obj)
        passing_assessments = passing_assessments_to_dict(assessment_status.passing_assessments)

        context = {
            "brand": brand,
            "has_downloadable_content": has_downloadable_content,
            "product": product,
            # Server-side rendered data (replacing Vue components)
            "public_projects": public_projects,
            "public_releases": public_releases,
            "product_identifiers": product_identifiers,
            "product_links": product_links,
            "view_all_releases_url": view_all_releases_url,
            # Assessment status (only passing assessments for public display)
            "passing_assessments": passing_assessments,
            "has_passing_assessments": assessment_status.all_pass,
        }
        add_custom_domain_to_context(request, context, team)

        return render(request, "core/product_details_public.html.j2", context)

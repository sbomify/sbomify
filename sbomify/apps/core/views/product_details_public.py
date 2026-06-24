from __future__ import annotations

from typing import Any

from django.db.models import Count, Exists, OuterRef
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.core.apis import get_product
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import LATEST_RELEASE_NAME, Release, ReleaseArtifact
from sbomify.apps.core.url_utils import (
    add_custom_domain_to_context,
    build_custom_domain_url,
    get_back_url_from_referrer,
    get_public_path,
    get_workspace_public_url,
    resolve_product_identifier,
    should_redirect_to_clean_url,
    should_redirect_to_custom_domain,
)
from sbomify.apps.plugins.public_assessment_utils import (
    get_product_latest_sbom_assessment_status,
    passing_assessments_to_dict,
)
from sbomify.apps.sboms.models import SBOM, ProductIdentifier, ProductLink
from sbomify.apps.tea.mappers import build_product_tei_urn
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team

# GTIN types that support barcode rendering
BARCODE_TYPES = ("gtin_12", "gtin_13", "gtin_14", "gtin_8")


def _prepare_public_components(product_id: str, is_custom_domain: bool) -> list[Any]:
    """Prepare component data for display on the public product page.

    Uses batch query for assessment status to avoid N+1 queries.
    """
    from sbomify.apps.core.models import Component
    from sbomify.apps.core.url_utils import get_public_path
    from sbomify.apps.plugins.public_assessment_utils import (
        get_components_latest_sbom_assessments_batch,
        passing_assessments_to_dict,
    )

    components = list(
        Component.objects.filter(
            products__id=product_id,
            visibility__in=(Component.Visibility.PUBLIC, Component.Visibility.GATED),
        )
        .order_by("name")
        .distinct()
    )

    assessments_by_component = get_components_latest_sbom_assessments_batch(components)

    public_components = []
    for component in components:
        passing_assessments = passing_assessments_to_dict(assessments_by_component.get(str(component.id), []))
        public_components.append(
            {
                "id": component.id,
                "name": component.name,
                "slug": component.slug,
                "component_type": component.component_type,
                "component_type_display": component.get_component_type_display(),
                "passing_assessments": passing_assessments,
                "public_url": get_public_path(
                    "component", component.id, is_custom_domain=is_custom_domain, slug=component.slug
                ),
            }
        )

    return public_components


def _get_public_releases(product_id: str, is_custom_domain: bool, product_slug: str, limit: int = 5) -> list[Any]:
    """Get releases for a public product (releases inherit visibility from their product)."""
    # Use annotations to avoid N+1 queries for artifacts_count and has_sboms
    # Exclude the synthetic auto-`latest` release — the product page surfaces it
    # via the "Download Latest Release" CTA, so it shouldn't also occupy a row
    # in the releases table.
    releases = (
        Release.objects.filter(product_id=product_id)
        .exclude(name=LATEST_RELEASE_NAME)
        .select_related("product")
        .annotate(
            annotated_artifacts_count=Count("artifacts"),
            annotated_has_sboms=Exists(ReleaseArtifact.objects.filter(release=OuterRef("pk"), sbom__isnull=False)),
        )
        # Reuse the model's default ordering (which sorts NULL released_at LAST,
        # so unreleased rows don't float to the top) and append ``name`` as a
        # stable tiebreaker: releases sharing a timestamp — seeded together, or
        # under the frozen clock used by e2e snapshots — would otherwise sort
        # arbitrarily and reorder the releases table run to run.
        .order_by(*(Release._meta.ordering or []), "name")[:limit]
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


def _get_product_identifiers(product_id: str) -> list[Any]:
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


def _get_product_links(product_id: str) -> list[Any]:
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
        # require_public=True filters at query level, preventing race conditions
        product_obj = resolve_product_identifier(request, product_id, require_public=True)
        if not product_obj:
            return error_response(request, HttpResponseNotFound("Product not found"))

        # Use the resolved product's ID for API calls
        resolved_id = product_obj.id

        status_code, product = get_product(request, resolved_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=product.get("detail", "Unknown error"))
            )

        has_downloadable_content = SBOM.objects.filter(component__products__id=resolved_id).exists()
        team = Team.objects.filter(pk=product.get("team_id")).first()

        # Redirect to custom domain if team has a verified one and we're not already on it
        # OR redirect from /public/ URL to clean URL on custom domain
        if team and (should_redirect_to_custom_domain(request, team) or should_redirect_to_clean_url(request)):
            path = get_public_path("product", resolved_id, is_custom_domain=True, slug=product_obj.slug)
            return HttpResponseRedirect(build_custom_domain_url(team, path, request.is_secure()))

        brand = build_branding_context(team)
        is_custom_domain = getattr(request, "is_custom_domain", False)

        # Get workspace public URL for breadcrumbs and back link fallback
        workspace_public_url = get_workspace_public_url(request, team)

        # Get back URL from referrer, with fallback to workspace
        back_url = get_back_url_from_referrer(request, team, workspace_public_url)

        # Prepare server-side data for Django templates
        public_components = _prepare_public_components(resolved_id, is_custom_domain)
        public_releases = _get_public_releases(
            resolved_id, is_custom_domain, product.get("slug") or resolved_id, limit=3
        )
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
        # Uses latest SBOM per component only (not all SBOMs)
        assessment_status = get_product_latest_sbom_assessment_status(product_obj)
        passing_assessments = passing_assessments_to_dict(assessment_status.passing_assessments)

        # Build TEI URN if TEA is enabled with a validated custom domain
        product_tei = build_product_tei_urn(product_obj.uuid, team, is_public=product_obj.is_public) if team else None

        # Check if VDP exists for this product
        from sbomify.apps.compliance.models import CRAAssessment, CRAGeneratedDocument

        has_vdp = CRAGeneratedDocument.objects.filter(
            assessment__product_id=product_obj.id,
            document_kind=CRAGeneratedDocument.DocumentKind.VDP,
        ).exists()

        # Expose the EU Declaration of Conformity only when (a) the
        # assessment is in ``complete`` status, (b) the DoC has been
        # rendered, and (c) the DoC has not been flagged stale by a
        # downstream change (product rename, manufacturer update,
        # control flip). Partial / draft / stale documents are not
        # authoritative — surfacing them on the public trust center
        # would mislead auditors and customers.
        has_doc = CRAGeneratedDocument.objects.filter(
            assessment__product_id=product_obj.id,
            assessment__status=CRAAssessment.WizardStatus.COMPLETE,
            document_kind=CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY,
            is_stale=False,
        ).exists()

        # Fetch public compliance controls for this product (if controls app is available)
        controls_summary = None
        controls_summary_list: list[dict[str, Any]] = []
        try:
            from sbomify.apps.controls.services.public_service import get_public_product_controls_list

            list_result = get_public_product_controls_list(product_obj)
            if list_result.ok and list_result.value:
                controls_summary_list = list_result.value
                controls_summary = controls_summary_list[0] if controls_summary_list else None
        except ModuleNotFoundError:
            pass

        context = {
            "brand": brand,
            "has_downloadable_content": has_downloadable_content,
            "product": product,
            "product_tei": product_tei,
            # Server-side rendered data
            "public_components": public_components,
            "public_releases": public_releases,
            "product_identifiers": product_identifiers,
            "product_links": product_links,
            "view_all_releases_url": view_all_releases_url,
            # Barcode types for identifier rendering
            "barcode_types": BARCODE_TYPES,
            # Assessment status (only passing assessments for public display)
            "passing_assessments": passing_assessments,
            "has_passing_assessments": assessment_status.all_pass,
            # Workspace URL for breadcrumbs
            "workspace_public_url": workspace_public_url,
            # Back URL from referrer or fallback
            "back_url": back_url,
            "fallback_url": workspace_public_url,
            # VDP availability
            "has_vdp": has_vdp,
            # Declaration of Conformity availability (CRA Annex V)
            "has_doc": has_doc,
            "preferred_base_url": build_custom_domain_url(team, "/", request.is_secure()).rstrip("/") if team else "",
            # Compliance controls summary
            "controls_summary": controls_summary,
            "controls_summary_list": controls_summary_list,
        }
        add_custom_domain_to_context(request, context, team)

        return render(request, "core/product_details_public.html.j2", context)

from __future__ import annotations

from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_release
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Product, Release
from sbomify.apps.core.services.release_links import release_link_rows
from sbomify.apps.core.url_utils import (
    add_custom_domain_to_context,
    custom_domain_redirect,
    get_public_path,
    get_release_public_slugs,
    get_workspace_public_url,
    resolve_product_identifier,
    resolve_release_identifier,
    should_redirect_to_clean_url,
    should_redirect_to_custom_domain,
)
from sbomify.apps.teams.branding import build_branding_context


class ReleaseDetailsPublicView(View):
    def get(self, request: HttpRequest, product_id: str, release_id: str) -> HttpResponse:
        # First resolve the product by slug (on custom domains) or ID (on main app)
        # require_public=True filters at query level, preventing race conditions
        product_obj = resolve_product_identifier(request, product_id, require_public=True)
        if not product_obj:
            return error_response(request, HttpResponseNotFound("Product not found"))

        # Then resolve the release by slug (on custom domains) or ID (on main app)
        release_obj = resolve_release_identifier(request, product_obj, release_id)
        if not release_obj:
            return error_response(request, HttpResponseNotFound("Release not found"))

        # Use the resolved release's ID for API calls
        resolved_release_id = release_obj.id

        status_code, release = get_release(request, resolved_release_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=release.get("detail", "Unknown error"))
            )

        product = Product.objects.select_related("team").filter(pk=release.get("product_id")).first()
        team = getattr(product, "team", None)

        # Redirect to custom domain if team has a verified one and we're not already on it
        # OR redirect from /public/ URL to clean URL on custom domain
        if team and (should_redirect_to_custom_domain(request, team) or should_redirect_to_clean_url(request)):
            path = get_public_path(
                "release",
                resolved_release_id,
                is_custom_domain=True,
                product_id=product_obj.id,
                product_slug=product_obj.slug,
                release_slug=release_obj.slug,
            )
            redirect = custom_domain_redirect(team, path, request.is_secure())
            if redirect is not None:
                return redirect

        brand = build_branding_context(team)

        # Get workspace public URL for breadcrumbs
        workspace_public_url = get_workspace_public_url(request, team)

        # The release's VEX-applied posture, published only where the workspace
        # has asked for it to be. A Trust Center is readable by anyone holding
        # the link, so which vulnerabilities a workspace is carrying stays the
        # workspace's own to disclose. This page shows what the public sees, to
        # members too: they read the full posture inside the app.
        from sbomify.apps.core.services.release_lifecycle import untracked_notice
        from sbomify.apps.vulnerability_scanning.posture import build_release_vuln_posture

        if team and team.publish_vulnerability_posture:
            vuln_posture = build_release_vuln_posture(release_obj)
        else:
            vuln_posture = {"has_data": False}

        is_custom_domain = bool(getattr(request, "is_custom_domain", False))

        def public_url(linked: Release) -> str:
            product_identifier = linked.product.slug or linked.product_id
            if is_custom_domain:
                slug_owner = resolve_product_identifier(request, product_identifier, require_public=True)
                if slug_owner is None or slug_owner.id != linked.product_id:
                    product_identifier = linked.product_id
            return get_public_path(
                "release",
                linked.id,
                is_custom_domain=is_custom_domain,
                product_id=linked.product_id,
                product_slug=product_identifier,
                release_slug=get_release_public_slugs(linked.product).get(linked.id, linked.id),
            )

        context = {
            "brand": brand,
            "release": release,
            # The public page shows what the public sees, to members too.
            "linked_releases": release_link_rows(release_obj, include_private=False, url_for=public_url),
            "vuln_posture": vuln_posture,
            # A release sbomify no longer monitors keeps the posture of its last
            # scan, and the page says how old that is.
            "untracked": untracked_notice(release_obj, public_only=True) if vuln_posture.get("has_data") else None,
            # `product` is consumed by the breadcrumb tag so the release page
            # gets a `Trust Center > Product` breadcrumb consistent with the
            # releases list and component pages. The current release isn't
            # added as a crumb — the page H1 already conveys it.
            "product": product,
            "workspace_public_url": workspace_public_url,
        }
        add_custom_domain_to_context(request, context, team)

        # Use slugs only where they resolve to the same product and release.
        # Products whose slug is empty or resolves elsewhere retain their ID.
        if getattr(request, "is_custom_domain", False):
            product_slug = product_obj.slug
            slug_owner = (
                resolve_product_identifier(request, product_slug, require_public=True) if product_slug else None
            )
            product_identifier = product_slug if slug_owner and slug_owner.id == product_obj.id else product_obj.id
            canonical_path = get_public_path(
                "release",
                resolved_release_id,
                is_custom_domain=True,
                product_id=product_obj.id,
                product_slug=product_identifier,
                release_slug=get_release_public_slugs(product_obj).get(resolved_release_id, resolved_release_id),
            )
            context["canonical_url"] = request.build_absolute_uri(canonical_path)

        return render(request, "core/release_details_public.html.j2", context)

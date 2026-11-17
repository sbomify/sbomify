"""The "Ships with" card on the release page: list, add and remove linked releases.

Writes go through the API functions, so the app and the API share one set of
permission checks, validation and broadcasts.
"""

from __future__ import annotations

from typing import Any

from django.db.models import F
from django.http import HttpRequest
from django.urls import reverse

from sbomify.apps.core.authz import can
from sbomify.apps.core.models import Release
from sbomify.apps.core.services.release_links import release_link_rows
from sbomify.apps.core.services.results import ServiceResult


def build_release_links_context(request: HttpRequest, release_id: str) -> ServiceResult[dict[str, Any]]:
    release = Release.objects.select_related("product").filter(pk=release_id).first()
    if release is None:
        return ServiceResult.failure("Release not found", status_code=404)
    if not can(request, "release:read", release.product):
        return ServiceResult.failure("Release not found", status_code=404)

    linked_releases = release_link_rows(
        release,
        include_private=True,
        url_for=lambda linked: reverse("core:release_details", args=[linked.product_id, linked.id]),
    )
    can_manage = bool(can(request, "release:manage", release.product)) and not release.is_latest

    candidates: list[dict[str, Any]] = []
    if can_manage:
        linked_ids = [row["id"] for row in linked_releases]
        others = (
            Release.objects.filter(product__team_id=release.product.team_id)
            .exclude(product_id=release.product_id)
            .exclude(pk__in=linked_ids)
            .select_related("product")
            .order_by("product__name", F("released_at").desc(nulls_last=True), "-created_at")
        )
        for other in others:
            if not candidates or candidates[-1]["product_id"] != other.product_id:
                candidates.append({"product_id": other.product_id, "product_name": other.product.name, "releases": []})
            candidates[-1]["releases"].append({"id": other.id, "label": other.version or other.name})

    return ServiceResult.success(
        {
            "links_release_id": release.id,
            "links_product_id": release.product_id,
            "linked_releases": linked_releases,
            "can_manage_links": can_manage,
            "link_candidates": candidates,
        }
    )


def handle_release_links_action(request: HttpRequest, release_id: str) -> ServiceResult[None]:
    from sbomify.apps.core.apis import link_release_to_release, unlink_release_from_release
    from sbomify.apps.core.schemas import ReleaseLinkCreateSchema

    action = request.POST.get("action")
    linked_release_id = request.POST.get("linked_release_id", "").strip()
    if not linked_release_id:
        return ServiceResult.failure("Choose a release")

    if action == "add":
        status_code, result = link_release_to_release(
            request, release_id, ReleaseLinkCreateSchema(release_id=linked_release_id)
        )
        if status_code != 201:
            return ServiceResult.failure(result.get("detail", "Failed to link the release"), status_code=status_code)
    elif action == "remove":
        status_code, result = unlink_release_from_release(request, release_id, linked_release_id)
        if status_code != 204:
            return ServiceResult.failure(
                (result or {}).get("detail", "Failed to remove the link"), status_code=status_code
            )
    else:
        return ServiceResult.failure("Unknown action")
    return ServiceResult.success()

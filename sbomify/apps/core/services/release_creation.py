"""Workspace-scoped choices and the existing API's release creation rules."""

from typing import Any

from django.http import HttpRequest

from sbomify.apps.core.apis import create_release
from sbomify.apps.core.authz import can
from sbomify.apps.core.models import Product
from sbomify.apps.core.schemas import ReleaseCreateSchema
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.teams.models import Team


def release_product_choices(request: HttpRequest) -> ServiceResult[list[tuple[str, str]]]:
    workspace_key = (request.session.get("current_team") or {}).get("key")
    workspace = Team.objects.filter(key=workspace_key).first() if workspace_key else None
    if workspace is None or not can(request, "release:create", workspace):
        return ServiceResult.failure("You cannot create releases in this workspace.", status_code=403)
    return ServiceResult.success(
        list(Product.objects.filter(team=workspace).order_by("name", "id").values_list("id", "name"))
    )


def create_workspace_release(request: HttpRequest, data: dict[str, Any]) -> ServiceResult[dict[str, Any]]:
    workspace_key = (request.session.get("current_team") or {}).get("key")
    product = Product.objects.select_related("team").filter(id=data["product_id"], team__key=workspace_key).first()
    if product is None or not can(request, "release:create", product):
        return ServiceResult.failure("Choose a product from this workspace.", status_code=403)
    status, result = create_release(request, ReleaseCreateSchema(**data))
    if status == 201:
        return ServiceResult.success(result)
    if status == 200:
        return ServiceResult.failure("A release with this name already exists for this product.")
    return ServiceResult.failure(result.get("detail", "Unable to create the release."), status_code=status)

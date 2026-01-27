from __future__ import annotations

from django.http import HttpRequest

from sbomify.apps.core.apis import get_component, list_component_sboms
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.sboms.forms import SbomDeleteForm
from sbomify.apps.sboms.services.sboms import delete_sbom_record
from sbomify.apps.teams.apis import get_team


def build_sboms_table_context(request: HttpRequest, component_id: str, is_public_view: bool) -> ServiceResult[dict]:
    status_code, component = get_component(request, component_id)
    if status_code != 200:
        return ServiceResult.failure(component.get("detail", "Unknown error"))

    status_code, sboms = list_component_sboms(request, component_id, page=1, page_size=-1)
    if status_code != 200:
        return ServiceResult.failure(sboms.get("detail", "Failed to load SBOMs"))

    sbom_items = sboms.get("items", [])

    # Sort SBOMs by name (alphabetically) then by created_at (newest first)
    sbom_items = sorted(
        sbom_items,
        key=lambda x: (
            x["sbom"]["name"].lower(),
            -x["sbom"]["created_at"].timestamp() if x["sbom"]["created_at"] else 0,
        ),
    )

    # Enrich each SBOM with passing assessments for compact icon display
    from sbomify.apps.plugins.public_assessment_utils import (
        get_sbom_passing_assessments,
        passing_assessments_to_dict,
    )

    for item in sbom_items:
        sbom_id = item.get("sbom", {}).get("id")
        if sbom_id:
            passing = get_sbom_passing_assessments(sbom_id)
            item["passing_assessments"] = passing_assessments_to_dict(passing)
        else:
            item["passing_assessments"] = []

    context = {
        "component_id": component_id,
        "sboms": sbom_items,
        "is_public_view": is_public_view,
        "has_crud_permissions": component.get("has_crud_permissions", False),
    }

    if not is_public_view:
        team_key = number_to_random_token(component.get("team_id"))
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return ServiceResult.failure(team.get("detail", "Failed to load team"))

        context.update(
            {
                "team_billing_plan": team.billing_plan,
                "team_key": team_key,
                "delete_form": SbomDeleteForm(),
            }
        )

    return ServiceResult.success(context)


def delete_sbom_from_request(request: HttpRequest) -> ServiceResult[None]:
    form = SbomDeleteForm(request.POST)
    if not form.is_valid():
        return ServiceResult.failure(form.errors.as_text())

    result = delete_sbom_record(request, form.cleaned_data["sbom_id"])
    if not result.ok:
        return ServiceResult.failure(result.error or "Failed to delete SBOM", status_code=result.status_code)

    return ServiceResult.success()

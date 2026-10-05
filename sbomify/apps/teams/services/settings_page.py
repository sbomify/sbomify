"""Shared settings context for initial pages and HTMX refreshes."""

from typing import Any, cast

from django.core.cache import cache
from django.db import transaction
from django.http import HttpRequest
from django.template.defaultfilters import date as date_filter

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.forms import CreateAccessTokenForm
from sbomify.apps.core.models import User
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.core.utils import token_to_number
from sbomify.apps.teams.apis import get_team_branding
from sbomify.apps.teams.forms import ContactProfileForm, PatchSLAForm
from sbomify.apps.teams.models import Member, Team, default_patch_sla_days


def general_context(request: HttpRequest, workspace_key: str) -> ServiceResult[dict[str, Any]]:
    membership = (
        Member.objects.select_related("team").filter(user=cast(User, request.user), team__key=workspace_key).first()
    )
    targets = membership.team.patch_sla_days if membership else default_patch_sla_days()
    workspace = membership.team if membership else None
    support_period = workspace.default_support_period_years if workspace else None
    # Each form's starting values, for the shared dirty-tracking component. They
    # are strings so an emptied field compares equal to an unset one.
    patch_sla_fields = {"mode": "recommended" if targets == default_patch_sla_days() else "custom"}
    patch_sla_fields.update({severity: _as_field_value(days) for severity, days in targets.items()})
    return ServiceResult.success(
        {
            "is_default_team": bool(membership and membership.is_default_team),
            "default_support_period_years": support_period,
            "patch_sla_form": PatchSLAForm(initial=targets),
            "team_general_fields": {
                "name": workspace.name if workspace else "",
                "sbom_freshness_days": _as_field_value(workspace.sbom_freshness_days if workspace else None),
            },
            "patch_sla_fields": patch_sla_fields,
            "support_period_fields": {"default_support_period_years": _as_field_value(support_period)},
        }
    )


def _as_field_value(value: Any) -> str:
    """A form field's value as the browser will report it: a string, blank when unset."""
    return "" if value is None else str(value)


def tokens_context(request: HttpRequest, workspace_key: str) -> ServiceResult[dict[str, Any]]:
    # Personal tokens must always be scoped to the caller, including legacy tokens.
    user = cast(User, request.user)
    unscoped = AccessToken.objects.filter(user=user, team__isnull=True).order_by("-created_at")
    return ServiceResult.success(
        {
            "create_access_token_form": CreateAccessTokenForm(),
            "access_tokens": AccessToken.objects.filter(user=user, team_id=token_to_number(workspace_key)).order_by(
                "-created_at"
            ),
            "unscoped_tokens": unscoped,
            "has_unscoped_tokens": unscoped.exists(),
        }
    )


def build_panel_context(request: HttpRequest, workspace_key: str, tab: str) -> ServiceResult[dict[str, Any]]:
    if tab == "controls":
        from sbomify.apps.controls.services.page_context import build_controls_settings

        return build_controls_settings(request, workspace_key)
    if tab == "general":
        return general_context(request, workspace_key)
    if tab == "tokens":
        return tokens_context(request, workspace_key)
    if tab == "branding":
        status, branding = get_team_branding(request, workspace_key)
        if status != 200:
            return ServiceResult.failure("Unable to load branding settings.", status_code=status)
        return ServiceResult.success({"branding_info": branding})
    return ServiceResult.success({})


def update_patch_sla(workspace_key: str, targets: dict[str, int | None]) -> ServiceResult[None]:
    with transaction.atomic():
        workspace = Team.objects.select_for_update().filter(key=workspace_key).first()
        if workspace is None:
            return ServiceResult.failure("Workspace not found", status_code=404)
        workspace.patch_sla_days = targets
        workspace.save(update_fields=["patch_sla_days"])
        transaction.on_commit(lambda: cache.delete(f"dashboard-page:v3:{workspace.pk}"))
    return ServiceResult.success()


def update_support_period(workspace_key: str, years: int | None) -> ServiceResult[None]:
    if not Team.objects.filter(key=workspace_key).update(default_support_period_years=years):
        return ServiceResult.failure("Workspace not found", status_code=404)
    return ServiceResult.success()


def profiles_context(profiles: Any) -> dict[str, Any]:
    rows = []
    for schema in profiles:
        profile = schema.model_dump()
        entities = profile.get("entities", [])
        profile["entity_count"] = len(entities)
        profile["author_count"] = len(profile.get("authors", []))
        profile["contact_count"] = sum(len(entity.get("contacts", [])) for entity in entities)
        profile["manufacturer"] = next((entity for entity in entities if entity.get("is_manufacturer")), None)
        profile["supplier"] = next((entity for entity in entities if entity.get("is_supplier")), None)
        # Formatted here rather than in the browser: the rest of settings renders
        # dates through the date filter, and toLocaleDateString put a second
        # format on the same page for anyone outside en-GB.
        profile["updated_display"] = date_filter(profile.get("updated_at"), "j M Y") or ""
        rows.append(profile)
    return {"profiles": rows, "form": ContactProfileForm()}

"""API endpoints for the plugins framework."""

from typing import Any

from django.db.models import OuterRef, Subquery
from django.http import HttpRequest
from ninja import Router
from pydantic import BaseModel

from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Team

from .models import AssessmentRun, RegisteredPlugin, TeamPluginSettings
from .schemas import (
    AssessmentBadgeData,
    AssessmentRunSchema,
    AssessmentStatusSummary,
    SBOMAssessmentsResponse,
)
from .sdk.enums import RunStatus

router = Router(tags=["plugins"])


def _run_to_schema(run: AssessmentRun) -> AssessmentRunSchema:
    """Convert an AssessmentRun model to schema."""
    # Try to get display name from registered plugin
    display_name = None
    try:
        plugin = RegisteredPlugin.objects.get(name=run.plugin_name)
        display_name = plugin.display_name
    except RegisteredPlugin.DoesNotExist:
        pass

    return AssessmentRunSchema(
        id=str(run.id),
        sbom_id=str(run.sbom_id),
        plugin_name=run.plugin_name,
        plugin_version=run.plugin_version,
        plugin_display_name=display_name,
        category=run.category,
        run_reason=run.run_reason,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error_message=run.error_message or None,
        result=run.result,
        created_at=run.created_at,
    )


def _compute_status_summary(runs: list[AssessmentRun]) -> AssessmentStatusSummary:
    """Compute status summary from a list of runs."""
    if not runs:
        return AssessmentStatusSummary(overall_status="no_assessments")

    passing = 0
    failing = 0
    pending = 0
    in_progress = 0

    for run in runs:
        if run.status == RunStatus.COMPLETED.value:
            # Check if any findings failed
            result = run.result or {}
            summary = result.get("summary", {})
            if summary.get("fail_count", 0) > 0 or summary.get("error_count", 0) > 0:
                failing += 1
            else:
                passing += 1
        elif run.status == RunStatus.PENDING.value:
            pending += 1
        elif run.status == RunStatus.RUNNING.value:
            in_progress += 1
        elif run.status == RunStatus.FAILED.value:
            failing += 1

    # Determine overall status
    if in_progress > 0:
        overall_status = "in_progress"
    elif pending > 0:
        overall_status = "pending"
    elif failing > 0:
        overall_status = "has_failures"
    elif passing > 0:
        overall_status = "all_pass"
    else:
        overall_status = "no_assessments"

    return AssessmentStatusSummary(
        overall_status=overall_status,
        total_assessments=len(runs),
        passing_count=passing,
        failing_count=failing,
        pending_count=pending,
        in_progress_count=in_progress,
    )


@router.get("/assessments/{sbom_id}", response=SBOMAssessmentsResponse)
def get_sbom_assessments(request: HttpRequest, sbom_id: str) -> SBOMAssessmentsResponse:
    """Get all assessment runs for an SBOM.

    Returns both the latest run per plugin and the full history.
    """
    # Verify SBOM exists
    if not SBOM.objects.filter(id=sbom_id).exists():
        return SBOMAssessmentsResponse(
            sbom_id=sbom_id,
            status_summary=AssessmentStatusSummary(overall_status="no_assessments"),
            latest_runs=[],
            all_runs=[],
        )

    # Get all runs for this SBOM
    all_runs = list(AssessmentRun.objects.filter(sbom_id=sbom_id).order_by("-created_at"))

    # Get latest run per plugin using a subquery
    latest_run_ids = (
        AssessmentRun.objects.filter(sbom_id=sbom_id)
        .values("plugin_name")
        .annotate(
            latest_id=Subquery(
                AssessmentRun.objects.filter(sbom_id=sbom_id, plugin_name=OuterRef("plugin_name"))
                .order_by("-created_at")
                .values("id")[:1]
            )
        )
        .values_list("latest_id", flat=True)
    )
    latest_runs = [run for run in all_runs if run.id in list(latest_run_ids)]

    # Compute status summary from latest runs only
    status_summary = _compute_status_summary(latest_runs)

    return SBOMAssessmentsResponse(
        sbom_id=sbom_id,
        status_summary=status_summary,
        latest_runs=[_run_to_schema(run) for run in latest_runs],
        all_runs=[_run_to_schema(run) for run in all_runs],
    )


@router.get("/assessments/{sbom_id}/badge", response=AssessmentBadgeData)
def get_sbom_assessment_badge(request: HttpRequest, sbom_id: str) -> AssessmentBadgeData:
    """Get minimal assessment data for badge display.

    Returns only what's needed for the assessment badge component.
    """
    # Get latest run per plugin
    latest_run_ids = (
        AssessmentRun.objects.filter(sbom_id=sbom_id)
        .values("plugin_name")
        .annotate(
            latest_id=Subquery(
                AssessmentRun.objects.filter(sbom_id=sbom_id, plugin_name=OuterRef("plugin_name"))
                .order_by("-created_at")
                .values("id")[:1]
            )
        )
        .values_list("latest_id", flat=True)
    )

    latest_runs = list(AssessmentRun.objects.filter(id__in=latest_run_ids))
    status_summary = _compute_status_summary(latest_runs)

    # Build per-plugin summary
    plugins: list[dict[str, Any]] = []
    for run in latest_runs:
        # Try to get display name
        display_name = run.plugin_name
        try:
            plugin = RegisteredPlugin.objects.get(name=run.plugin_name)
            display_name = plugin.display_name
        except RegisteredPlugin.DoesNotExist:
            pass

        # Determine plugin status
        if run.status == RunStatus.COMPLETED.value:
            result = run.result or {}
            summary = result.get("summary", {})
            if summary.get("fail_count", 0) > 0 or summary.get("error_count", 0) > 0:
                plugin_status = "fail"
            else:
                plugin_status = "pass"
            findings_count = summary.get("total_findings", 0)
        elif run.status in (RunStatus.PENDING.value, RunStatus.RUNNING.value):
            plugin_status = "pending"
            findings_count = 0
        else:
            plugin_status = "error"
            findings_count = 0

        plugins.append(
            {
                "name": run.plugin_name,
                "display_name": display_name,
                "status": plugin_status,
                "findings_count": findings_count,
                "fail_count": (run.result or {}).get("summary", {}).get("fail_count", 0),
            }
        )

    return AssessmentBadgeData(
        sbom_id=sbom_id,
        overall_status=status_summary.overall_status,
        total_assessments=status_summary.total_assessments,
        passing_count=status_summary.passing_count,
        failing_count=status_summary.failing_count,
        pending_count=status_summary.pending_count,
        plugins=plugins,
    )


@router.get("/registered", response=list[dict])
def get_registered_plugins(request: HttpRequest) -> list[dict]:
    """Get all registered and enabled plugins."""
    plugins = RegisteredPlugin.objects.filter(is_enabled=True)
    return [
        {
            "name": p.name,
            "display_name": p.display_name,
            "description": p.description,
            "category": p.category,
            "version": p.version,
            "is_beta": p.is_beta,
        }
        for p in plugins
    ]


# Team Plugin Settings API


class TeamPluginSettingsResponse(BaseModel):
    """Response schema for team plugin settings."""

    team_key: str
    enabled_plugins: list[str]
    plugin_configs: dict[str, Any]
    available_plugins: list[dict[str, Any]]


class UpdateTeamPluginSettingsRequest(BaseModel):
    """Request schema for updating team plugin settings."""

    enabled_plugins: list[str]
    plugin_configs: dict[str, Any] | None = None


def _get_plugin_plan_requirement(plugin_name: str) -> str | None:
    """Get the required plan feature for a plugin.

    Returns the plan feature name or None if available to all plans.
    """
    # Map plugin names to their required plan features
    plan_requirements = {
        "ntia-minimum-elements-2021": "has_ntia_compliance",
        "fda-medical-device-2025": "has_fda_compliance",
        # Future plugins can be added here
        # "cisa-minimum-elements-2025": "has_cisa_compliance",
    }
    return plan_requirements.get(plugin_name)


def _check_team_has_plugin_access(team: Team, plugin_name: str) -> bool:
    """Check if a team's billing plan allows access to a plugin."""
    from sbomify.apps.billing.config import is_billing_enabled
    from sbomify.apps.billing.models import BillingPlan

    # If billing is disabled, grant access to all plugins
    if not is_billing_enabled():
        return True

    required_feature = _get_plugin_plan_requirement(plugin_name)
    if required_feature is None:
        return True  # No plan requirement

    if not team.billing_plan:
        return False  # No billing plan means community (free) tier

    try:
        plan = BillingPlan.objects.get(key=team.billing_plan)
        return getattr(plan, required_feature, False)
    except BillingPlan.DoesNotExist:
        return False


def get_team_plugin_settings(request: HttpRequest, team_key: str) -> tuple[int, dict]:
    """Get plugin settings for a team.

    Returns a tuple of (status_code, data).
    """
    try:
        team = Team.objects.get(key=team_key)
    except Team.DoesNotExist:
        return 404, {"detail": "Team not found"}

    # Get or create team plugin settings
    settings, _ = TeamPluginSettings.objects.get_or_create(team=team)

    # Get all available plugins with plan availability info
    available_plugins = []
    for p in RegisteredPlugin.objects.filter(is_enabled=True):
        has_access = _check_team_has_plugin_access(team, p.name)
        required_feature = _get_plugin_plan_requirement(p.name)

        available_plugins.append(
            {
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "category": p.category,
                "version": p.version,
                "default_config": p.default_config,
                "is_beta": p.is_beta,
                "has_access": has_access,
                "requires_upgrade": required_feature is not None and not has_access,
                "required_plan": "Business" if required_feature else None,
            }
        )

    return 200, {
        "team_key": team_key,
        "enabled_plugins": settings.enabled_plugins or [],
        "plugin_configs": settings.plugin_configs or {},
        "available_plugins": available_plugins,
        "team_plan": team.billing_plan or "community",
    }


def update_team_plugin_settings(
    request: HttpRequest, team_key: str, payload: UpdateTeamPluginSettingsRequest
) -> tuple[int, dict]:
    """Update plugin settings for a team.

    Returns a tuple of (status_code, data).
    """
    try:
        team = Team.objects.get(key=team_key)
    except Team.DoesNotExist:
        return 404, {"detail": "Team not found"}

    # Validate that all enabled plugins are registered and enabled
    available_plugins = set(RegisteredPlugin.objects.filter(is_enabled=True).values_list("name", flat=True))
    invalid_plugins = set(payload.enabled_plugins) - available_plugins
    if invalid_plugins:
        return 400, {"detail": f"Invalid plugins: {', '.join(invalid_plugins)}"}

    # Validate that team has access to all enabled plugins based on billing plan
    inaccessible_plugins = [
        plugin for plugin in payload.enabled_plugins if not _check_team_has_plugin_access(team, plugin)
    ]
    if inaccessible_plugins:
        return 403, {
            "detail": f"Your plan does not include access to: {', '.join(inaccessible_plugins)}. "
            "Please upgrade to enable these plugins."
        }

    # Get or create team plugin settings
    settings, _ = TeamPluginSettings.objects.get_or_create(team=team)

    # Update settings
    settings.enabled_plugins = payload.enabled_plugins
    if payload.plugin_configs is not None:
        settings.plugin_configs = payload.plugin_configs
    settings.save()

    return 200, {
        "message": "Plugin settings updated successfully",
        "enabled_plugins": settings.enabled_plugins,
        "plugin_configs": settings.plugin_configs,
    }

"""API endpoints for the plugins framework."""

from collections.abc import Callable
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


def _is_run_skipped(run: AssessmentRun) -> bool:
    """Check if an assessment run was skipped by the plugin (not actually scanned).

    Release-per-pair plugins (e.g. Dependency Track) return a skipped result
    when their preconditions aren't met — for example, a cron-triggered DT
    scan on an SBOM with no release association. The run completes (no
    error, no findings) but it shouldn't be counted as "passing" because
    the plugin never actually scanned anything. The plugin signals this
    via ``result.metadata.skipped = True``.
    """
    if not run.result or not isinstance(run.result, dict):
        return False
    metadata = run.result.get("metadata")
    if not isinstance(metadata, dict):
        return False
    return bool(metadata.get("skipped"))


def _is_run_failing(run: AssessmentRun) -> bool:
    """Check if a completed assessment run has issues.

    For security plugins: any vulnerability (total_findings > 0 from by_severity) is a failure.

    For compliance/attestation/other plugins: a run is failing when it has
    explicit failures or errors, OR when it produced *no* positive
    findings (``pass_count == 0`` with warnings only). The latter case
    closes a UI-side mirror of the orchestrator's warnings-only false
    positive: a plugin that emitted only warnings (e.g. the legacy
    github-attestation "no VCS info" warning) was counted as passing
    in the dashboard, despite verifying nothing. The badge now matches
    the dependency-gate verdict — if BSI's ``requires_one_of`` does not
    treat the run as passing, neither does the UI summary.

    Skipped runs are NOT failing — they never scanned, so they produced no
    findings. They're not passing either (see ``_compute_status_summary``).
    """
    if _is_run_skipped(run):
        return False

    if not run.result or not isinstance(run.result, dict):
        return False

    summary = run.result.get("summary")
    if not isinstance(summary, dict):
        return False

    if run.category == "security":
        by_severity = summary.get("by_severity") or {}
        total_from_severity: int = sum(
            by_severity.get(sev, 0) for sev in ("critical", "high", "medium", "low", "info", "unknown")
        )
        return total_from_severity > 0

    fail_count: int = summary.get("fail_count", 0)
    error_count: int = summary.get("error_count", 0)
    # Legacy summaries (predating ``pass_count`` tracking) lack the key
    # entirely; treat that as the old contract. Modern runs always
    # include the key — present-and-zero is the warnings-only signal.
    pass_count = summary.get("pass_count")
    if pass_count is None:
        return fail_count > 0 or error_count > 0
    return fail_count > 0 or error_count > 0 or pass_count == 0


def _get_plugin_display_names_map(plugin_names: set[str]) -> dict[str, str]:
    """Fetch display names for a set of plugin names in a single query.

    Avoids the N+1 query pattern that would result from looking up each
    run's plugin_name individually during schema conversion. Returns a
    dict mapping plugin_name → display_name.
    """
    if not plugin_names:
        return {}
    return {
        p.name: p.display_name
        for p in RegisteredPlugin.objects.filter(name__in=plugin_names).only("name", "display_name")
    }


def _run_to_schema(
    run: AssessmentRun,
    display_names: dict[str, str] | None = None,
) -> AssessmentRunSchema:
    """Convert an AssessmentRun model to schema.

    Args:
        run: The AssessmentRun to serialize.
        display_names: Optional prefetched map of plugin_name → display_name.
            Callers that serialize multiple runs should prefetch this once
            via ``_get_plugin_display_names_map`` to avoid N+1 queries.
            When None, falls back to a per-call DB lookup for backward
            compatibility with single-run callers.
    """
    if display_names is not None:
        display_name = display_names.get(run.plugin_name)
    else:
        # Fallback: legacy single-run callers
        display_name = None
        try:
            plugin = RegisteredPlugin.objects.only("display_name").get(name=run.plugin_name)
            display_name = plugin.display_name
        except RegisteredPlugin.DoesNotExist:
            pass

    # Populate release_ids from the M2M. Callers that want to avoid an N+1
    # per-run lookup should prefetch ``releases`` on the queryset before
    # calling this function — both batch serialization sites in this module
    # do that via _get_latest_assessment_runs_for_sbom and the API endpoint
    # querysets.
    # Sort in Python (not .order_by) to preserve the prefetch cache
    releases = sorted(run.releases.all(), key=lambda r: r.name)
    release_ids = [str(rel.id) for rel in releases]
    release_names = [rel.name for rel in releases]

    return AssessmentRunSchema(
        id=str(run.id),
        sbom_id=str(run.sbom_id),
        release_ids=release_ids,
        release_names=release_names,
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
    """Compute status summary from a list of runs.

    Skipped runs (see ``_is_run_skipped``) are tracked in their own count
    and do NOT inflate ``passing_count``. This prevents misleading "all
    green" reporting when a plugin like Dependency Track was triggered but
    didn't actually scan (e.g., SBOM had no release association).
    """
    if not runs:
        return AssessmentStatusSummary(overall_status="no_assessments")

    passing = 0
    failing = 0
    pending = 0
    in_progress = 0
    skipped = 0

    for run in runs:
        if run.status == RunStatus.COMPLETED.value:
            if _is_run_skipped(run):
                skipped += 1
            elif _is_run_failing(run):
                failing += 1
            else:
                passing += 1
        elif run.status == RunStatus.PENDING.value:
            pending += 1
        elif run.status == RunStatus.RUNNING.value:
            in_progress += 1
        elif run.status == RunStatus.FAILED.value:
            failing += 1

    # Determine overall status. Skipped is a neutral state — it does not
    # drive the overall_status field by itself; only pass/fail/pending do.
    if in_progress > 0:
        overall_status = "in_progress"
    elif pending > 0:
        overall_status = "pending"
    elif failing > 0:
        overall_status = "has_failures"
    elif passing > 0:
        overall_status = "all_pass"
    elif skipped > 0:
        # Only skipped runs — no real pass/fail signal. Treat as
        # "no assessments ran" from the user's perspective.
        overall_status = "no_assessments"
    else:
        overall_status = "no_assessments"

    return AssessmentStatusSummary(
        overall_status=overall_status,
        total_assessments=len(runs),
        passing_count=passing,
        failing_count=failing,
        pending_count=pending,
        in_progress_count=in_progress,
        skipped_count=skipped,
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

    # Get all runs for this SBOM, ordered newest-first. Prefetch the
    # ``releases`` M2M so per-run serialization doesn't trigger N+1.
    all_runs = list(AssessmentRun.objects.filter(sbom_id=sbom_id).prefetch_related("releases").order_by("-created_at"))

    # Latest-per-plugin selection: under the scan-once-per-SBOM model, each
    # plugin produces at most one current run for an SBOM, so a single pass
    # over the newest-first list picks the right row per plugin_name.
    seen_plugins: set[str] = set()
    latest_runs: list[AssessmentRun] = []
    for run in all_runs:
        if run.plugin_name in seen_plugins:
            continue
        seen_plugins.add(run.plugin_name)
        latest_runs.append(run)

    # Compute status summary from latest runs only
    status_summary = _compute_status_summary(latest_runs)

    # Prefetch display names for all plugin_names present in this response
    # in a single query so serialization stays O(n) without per-run lookups.
    display_names = _get_plugin_display_names_map({run.plugin_name for run in all_runs})

    return SBOMAssessmentsResponse(
        sbom_id=sbom_id,
        status_summary=status_summary,
        latest_runs=[_run_to_schema(run, display_names) for run in latest_runs],
        all_runs=[_run_to_schema(run, display_names) for run in all_runs],
    )


@router.get("/assessments/{sbom_id}/badge", response=AssessmentBadgeData)
def get_sbom_assessment_badge(request: HttpRequest, sbom_id: str) -> AssessmentBadgeData:
    """Get minimal assessment data for badge display.

    Returns only what's needed for the assessment badge component.
    """
    # Fetch only the latest run per plugin_name via Subquery/OuterRef —
    # bounded to ``enabled plugins per SBOM`` rather than the full run
    # history. Under the scan-once-per-SBOM model there's one run per
    # plugin per SBOM so this lookup is a simple group-by-plugin.
    latest_ids = list(
        AssessmentRun.objects.filter(sbom_id=sbom_id)
        .values("plugin_name")
        .annotate(
            latest_id=Subquery(
                AssessmentRun.objects.filter(
                    sbom_id=sbom_id,
                    plugin_name=OuterRef("plugin_name"),
                )
                .order_by("-created_at")
                .values("id")[:1]
            )
        )
        .values_list("latest_id", flat=True)
    )
    latest_ids = [pk for pk in latest_ids if pk is not None]
    latest_runs = list(AssessmentRun.objects.filter(id__in=latest_ids))
    status_summary = _compute_status_summary(latest_runs)

    # Prefetch display names once — avoids N+1 in the per-plugin loop below.
    display_names = _get_plugin_display_names_map({run.plugin_name for run in latest_runs})

    # Build per-plugin summary
    plugins: list[dict[str, Any]] = []
    for run in latest_runs:
        display_name = display_names.get(run.plugin_name, run.plugin_name)

        # Determine plugin status. "skipped" is its own status (distinct
        # from "pass") so frontends can render a neutral badge for runs
        # that completed without actually scanning (e.g., DT with no
        # release association).
        if run.status == RunStatus.COMPLETED.value:
            result = run.result or {}
            summary = result.get("summary", {})
            if _is_run_skipped(run):
                plugin_status = "skipped"
                findings_count = 0
            elif _is_run_failing(run):
                plugin_status = "fail"
                findings_count = summary.get("total_findings", 0)
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
        skipped_count=status_summary.skipped_count,
        plugins=plugins,
    )


@router.get("/registered", response=list[dict[str, Any]])
def get_registered_plugins(request: HttpRequest) -> list[dict[str, Any]]:
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
        "dependency-track": "has_dependency_track_access",
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


def _resolve_dt_servers(team: Team | None = None) -> list[dict[str, Any]]:
    """Resolve available Dependency Track servers for select field.

    Only Enterprise teams can select a specific server.
    Business/Community teams use the default shared pool (no choices shown).
    """
    if team is None:
        return []

    plan_key = (team.billing_plan or "").strip().lower()
    if plan_key != "enterprise":
        return []

    from sbomify.apps.vulnerability_scanning.models import DependencyTrackServer

    return [
        {"value": str(s.id), "label": s.name or f"Server {s.id}"}
        for s in DependencyTrackServer.objects.filter(is_active=True).order_by("priority", "name")
    ]


CHOICE_RESOLVERS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "dt_servers": _resolve_dt_servers,
}


def _resolve_config_schema(schema: list[dict[str, Any]], team: Team | None = None) -> list[dict[str, Any]]:
    """Resolve dynamic choices in a config schema.

    Replaces `choices_source` keys with resolved `choices` lists.

    Args:
        schema: List of field definitions from RegisteredPlugin.config_schema.
        team: The team to resolve choices for (used for plan-based filtering).

    Returns:
        Schema with dynamic choices resolved.
    """
    resolved = []
    for field in schema:
        field = {**field}  # shallow copy
        if field.get("choices_source"):
            resolver = CHOICE_RESOLVERS.get(field["choices_source"])
            if resolver:
                field["choices"] = resolver(team=team)
            del field["choices_source"]
        resolved.append(field)
    return resolved


def get_team_plugin_settings(request: HttpRequest, team_key: str) -> tuple[int, dict[str, Any]]:
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
                "config_schema": _resolve_config_schema(p.config_schema or [], team=team),
            }
        )

    # Sort: eligible plugins first, then ineligible (by display name within each group)
    available_plugins.sort(key=lambda p: (p["requires_upgrade"], p["display_name"]))

    return 200, {
        "team_key": team_key,
        "enabled_plugins": settings.enabled_plugins or [],
        "plugin_configs": settings.plugin_configs or {},
        "available_plugins": available_plugins,
        "team_plan": team.billing_plan or "community",
    }


def update_team_plugin_settings(
    request: HttpRequest, team_key: str, payload: UpdateTeamPluginSettingsRequest
) -> tuple[int, dict[str, Any]]:
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

    # Enforce tier restrictions on plugin configs
    if payload.plugin_configs is not None:
        plan_key = (team.billing_plan or "").strip().lower()
        if plan_key != "enterprise":
            # Non-enterprise teams cannot select a specific DT server
            dt_config = payload.plugin_configs.get("dependency-track")
            if isinstance(dt_config, dict):
                dt_config.pop("dt_server_id", None)

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

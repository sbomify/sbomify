"""Automated control status updates based on plugin assessment results.

This module maps plugin assessment outcomes to compliance controls. When a
plugin passes, the relevant controls can be automatically marked as
compliant (only if they are currently ``not_implemented`` so that manual
overrides are never overwritten).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import transaction

from sbomify.apps.controls.models import Control, ControlCatalog, ControlStatus, ControlStatusLog
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk.enums import RunStatus

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team

# Plugin name → list of SOC 2 control IDs that can be auto-verified.
PLUGIN_CONTROL_MAP: dict[str, list[str]] = {
    "ntia-minimum-elements-2021": ["CC2.1", "CC2.2", "CC2.3"],
    "osv": ["CC6.8", "CC7.1", "CC7.2", "CC7.3"],
    "dependency-track": ["CC6.8", "CC7.1", "CC7.2"],
    "checksum": ["CC6.6", "CC6.7"],
    # ``sbom-verification`` is the unified attestation plugin (formerly the
    # separate ``github-attestation`` plugin). It satisfies CC8.1 (Change
    # Management) by cryptographically verifying the SBOM artifact via any
    # of: cosign-bundle signature, SLSA provenance subject digest, or
    # GitHub-published Sigstore attestation.
    "sbom-verification": ["CC8.1"],
    "bsi-tr03183-v2.1-compliance": ["CC2.1", "CC5.1", "CC5.2"],
    "cra-compliance-2024": ["CC5.1", "CC5.2", "CC5.3"],
}


def get_automation_mappings() -> dict[str, list[str]]:
    """Return the plugin-to-control mapping for UI display."""
    return dict(PLUGIN_CONTROL_MAP)


def _is_passing(run: AssessmentRun) -> bool:
    """Determine whether an assessment run's result is passing.

    Mirrors ``PluginOrchestrator._is_passing`` — kept in sync because both
    feed downstream consumers (control-status promotion here, dependency
    gates in the orchestrator). For non-security plugins, "passing"
    requires at least one explicit pass finding so a warnings-only run
    cannot promote a control to ``compliant`` on no positive evidence.
    """
    if not run.result or not isinstance(run.result, dict):
        return False

    summary = run.result.get("summary")
    if not isinstance(summary, dict):
        return False

    if run.category == "security":
        by_severity: dict[str, int] = summary.get("by_severity") or {}
        total_from_severity: int = sum(
            by_severity.get(sev, 0) for sev in ("critical", "high", "medium", "low", "info", "unknown")
        )
        return total_from_severity == 0

    fail_count: int = summary.get("fail_count", 0)
    error_count: int = summary.get("error_count", 0)
    # Legacy summaries (from before pass_count was tracked) won't have
    # the key. Treat absent-key as the old contract so historical runs
    # don't retroactively flip from "promote control" to "don't promote".
    pass_count = summary.get("pass_count")
    if pass_count is None:
        return fail_count == 0 and error_count == 0
    return fail_count == 0 and error_count == 0 and pass_count > 0


def auto_update_from_assessment(team: Team, plugin_name: str, passed: bool) -> ServiceResult[int]:
    """Update control statuses based on a plugin assessment result.

    * If *passed* is ``True``, controls mapped to the plugin that currently
      have a ``not_implemented`` status are promoted to ``compliant``.
    * If *passed* is ``False``, no existing statuses are changed (manual
      overrides take precedence).

    Returns the count of controls whose status was updated.
    """
    control_ids = PLUGIN_CONTROL_MAP.get(plugin_name)
    if not control_ids:
        return ServiceResult.success(0)

    if not passed:
        return ServiceResult.success(0)

    # Find controls in this team's active catalogs that match the mapped IDs
    active_catalogs = ControlCatalog.objects.filter(team=team, is_active=True)
    controls = Control.objects.filter(catalog__in=active_catalogs, control_id__in=control_ids)

    if not controls.exists():
        return ServiceResult.success(0)

    updated_count = 0
    with transaction.atomic():
        for control in controls:
            # Check existing global status (product=None)
            existing = ControlStatus.objects.filter(control=control, product__isnull=True).first()

            if existing and existing.status != ControlStatus.Status.NOT_IMPLEMENTED:
                # Don't overwrite manual or partial statuses
                continue

            old_status = existing.status if existing else ""

            ControlStatus.objects.update_or_create(
                control=control,
                product=None,
                defaults={
                    "status": ControlStatus.Status.COMPLIANT,
                    "notes": f"Auto-set by {plugin_name} assessment",
                    "updated_by": None,
                },
            )

            # Log the change
            if old_status != ControlStatus.Status.COMPLIANT:
                ControlStatusLog.objects.create(
                    control=control,
                    product=None,
                    old_status=old_status,
                    new_status=ControlStatus.Status.COMPLIANT,
                    changed_by=None,
                )

            updated_count += 1

    return ServiceResult.success(updated_count)


def sync_from_latest_assessments(team: Team) -> ServiceResult[dict[str, Any]]:
    """Sync control statuses from the latest completed assessment runs for a team.

    Looks at the most recent ``AssessmentRun`` for each plugin, checks
    whether it passed, and delegates to :func:`auto_update_from_assessment`.

    Returns a summary dict: ``{"total_updated": int, "by_plugin": {name: count}}``.
    """
    # Get latest completed assessment run per plugin for SBOMs belonging to this team
    seen_plugins: set[str] = set()
    by_plugin: dict[str, int] = {}
    total_updated = 0

    for plugin_name in PLUGIN_CONTROL_MAP:
        if plugin_name in seen_plugins:
            continue
        seen_plugins.add(plugin_name)

        latest_run = (
            AssessmentRun.objects.filter(
                plugin_name=plugin_name,
                status=RunStatus.COMPLETED.value,
                sbom__component__team=team,
            )
            .order_by("-created_at")
            .first()
        )

        if not latest_run:
            continue

        passed = _is_passing(latest_run)
        result = auto_update_from_assessment(team, plugin_name, passed)
        if result.ok and result.value:
            by_plugin[plugin_name] = result.value
            total_updated += result.value

    return ServiceResult.success({"total_updated": total_updated, "by_plugin": by_plugin})

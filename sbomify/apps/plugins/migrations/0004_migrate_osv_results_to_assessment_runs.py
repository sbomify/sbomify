"""Data migration: convert VulnerabilityScanResult (provider=osv) to AssessmentRun records.

This migration reads existing OSV scan results from the vulnerability_scanning app
and creates corresponding AssessmentRun records in the plugins framework. The
original VulnerabilityScanResult records are preserved (DT also uses them, and
they serve as historical reference).
"""

import logging

from django.db import migrations

logger = logging.getLogger(__name__)

# Mapping from VulnerabilityScanResult.scan_trigger to RunReason values
TRIGGER_TO_REASON = {
    "upload": "on_upload",
    "manual": "manual",
    "api": "manual",
    "weekly": "scheduled_refresh",
    "component_latest": "scheduled_refresh",
}


def migrate_osv_results(apps, schema_editor):
    """Convert VulnerabilityScanResult (provider=osv) to AssessmentRun records."""
    VulnerabilityScanResult = apps.get_model("vulnerability_scanning", "VulnerabilityScanResult")
    AssessmentRun = apps.get_model("plugins", "AssessmentRun")

    osv_results = VulnerabilityScanResult.objects.filter(provider="osv").select_related("sbom")

    if not osv_results.exists():
        return

    batch = []
    for result in osv_results.iterator(chunk_size=500):
        # Map scan_trigger to run_reason
        run_reason = TRIGGER_TO_REASON.get(result.scan_trigger, "on_upload")

        # Convert findings to Finding-compatible dicts
        findings = []
        raw_findings = result.findings or []
        for f in raw_findings:
            if not isinstance(f, dict):
                continue
            findings.append(
                {
                    "id": f.get("id", "unknown"),
                    "title": f.get("title") or f.get("summary", "Unknown vulnerability"),
                    "description": f.get("description") or f.get("details", ""),
                    "severity": f.get("severity", "medium"),
                    "component": f.get("component"),
                    "cvss_score": None,
                    "references": f.get("references"),
                    "aliases": f.get("aliases"),
                }
            )

        # Build summary from vulnerability_count
        vuln_count = result.vulnerability_count or {}
        by_severity = {
            "critical": vuln_count.get("critical", 0),
            "high": vuln_count.get("high", 0),
            "medium": vuln_count.get("medium", 0),
            "low": vuln_count.get("low", 0),
            "info": vuln_count.get("info", 0),
            "unknown": vuln_count.get("unknown", 0),
        }

        assessment_result = {
            "schema_version": "1.0",
            "plugin_name": "osv",
            "plugin_version": "1.0.0",
            "category": "security",
            "assessed_at": result.created_at.isoformat(),
            "summary": {
                "total_findings": len(findings),
                "by_severity": by_severity,
            },
            "findings": findings,
            "metadata": {
                "migrated_from": "VulnerabilityScanResult",
                "original_id": str(result.id),
            },
        }

        batch.append(
            AssessmentRun(
                sbom_id=result.sbom_id,
                plugin_name="osv",
                plugin_version="1.0.0",
                plugin_config_hash="migrated",
                category="security",
                run_reason=run_reason,
                status="completed",
                result=assessment_result,
                result_schema_version="1.0",
                started_at=None,
                completed_at=result.created_at,
                created_at=result.created_at,
            )
        )

        if len(batch) >= 500:
            expected = len(batch)
            created = AssessmentRun.objects.bulk_create(batch, ignore_conflicts=True)
            if len(created) < expected:
                logger.warning(
                    "OSV migration: %d/%d records skipped (already exist)", expected - len(created), expected
                )
            batch = []

    if batch:
        expected = len(batch)
        created = AssessmentRun.objects.bulk_create(batch, ignore_conflicts=True)
        if len(created) < expected:
            logger.warning(
                "OSV migration: %d/%d records skipped (already exist)", expected - len(created), expected
            )


class Migration(migrations.Migration):
    dependencies = [
        ("plugins", "0003_add_plugin_dependencies"),
        ("vulnerability_scanning", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(migrate_osv_results, migrations.RunPython.noop),
    ]

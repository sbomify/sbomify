"""Vulnerability and risk-posture tools.

Vulnerability findings are produced by security-category assessment plugins (OSV,
Dependency-Track) and stored on ``AssessmentRun``. The numbers an agent reports
have to match the numbers a human sees on the dashboards, so this module reuses
the same three pieces of logic the UI does rather than re-deriving any of them:

* ``merge_findings_by_alias`` folds several providers' results for one SBOM into
  a single set of findings. Providers report the same issue under different ids
  (Dependency-Track the CVE, OSV the GHSA with the CVE as an alias), so summing
  per-provider counts would report roughly double the real figure.
* ``utils.is_vulnerability`` drops provider bookkeeping rows — scan errors and
  "no product" markers — which are not vulnerabilities and must not be handed to
  an agent as CVEs.
* ``extract_finding_rows`` flattens findings into display rows, resolving package
  identity out of the nested ``component`` object and carrying the VEX analysis
  state, so findings a customer has already dispositioned as ``not_affected``
  are visible as suppressed rather than counted as live.

Everything user-facing that originates in scanner output over supplier-supplied
SBOM content is passed through ``limits.untrusted`` before it reaches the model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import serializers
from ..auth import Principal, require
from ..limits import untrusted
from ._base import clamp_page, mcp_tool, resolve_workspace, run_db
from .catalog import _get_release, _lookup_component, _lookup_product

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from mcp.server.fastmcp import FastMCP

SEVERITIES = ("critical", "high", "medium", "low", "unknown")


def _security_runs(team: Any) -> QuerySet[Any]:
    """Every security assessment run for ``team``, newest first."""
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.sdk.enums import AssessmentCategory

    return (
        AssessmentRun.objects.filter(
            sbom__component__team=team,
            category=AssessmentCategory.SECURITY.value,
        )
        .select_related("sbom", "sbom__component")
        .order_by("sbom_id", "plugin_name", "-created_at")
    )


def _latest_per_provider(runs: QuerySet[Any]) -> dict[str, list[Any]]:
    """Group runs by SBOM, keeping the newest run per (sbom, plugin)."""
    seen: set[tuple[str, str]] = set()
    by_sbom: dict[str, list[Any]] = {}
    for run in runs:
        key = (run.sbom_id, run.plugin_name)
        if key in seen:
            continue
        seen.add(key)
        by_sbom.setdefault(run.sbom_id, []).append(run)
    return by_sbom


def _rows_for(runs: QuerySet[Any]) -> tuple[list[dict[str, Any]], set[str]]:
    """Flatten ``runs`` into finding rows, merged across providers.

    Returns ``(rows, scanned_sbom_ids)``. Each row carries the SBOM and component
    it came from so a finding can be traced back to what ships it.
    """
    from sbomify.apps.vulnerability_scanning.utils import (
        extract_finding_rows,
        is_vulnerability,
        merge_findings_by_alias,
    )

    rows: list[dict[str, Any]] = []
    scanned: set[str] = set()

    for sbom_id, sbom_runs in _latest_per_provider(runs).items():
        merged = merge_findings_by_alias([run.result for run in sbom_runs])
        merged["findings"] = [
            finding
            for finding in merged.get("findings") or []
            if isinstance(finding, dict) and is_vulnerability(finding)
        ]
        scanned.add(sbom_id)

        sbom = sbom_runs[0].sbom
        providers = sorted({run.plugin_name for run in sbom_runs})
        for row in extract_finding_rows(merged):
            row["sbom_id"] = sbom_id
            row["component_id"] = sbom.component_id
            row["component_name"] = sbom.component.name
            row["providers"] = providers
            rows.append(row)

    return rows, scanned


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Severity tally over live (non-VEX-suppressed) findings."""
    counts = dict.fromkeys(("total", *SEVERITIES), 0)
    for row in rows:
        if row.get("vex_suppressed"):
            continue
        raw_severity = row.get("severity")
        severity = raw_severity if raw_severity in SEVERITIES else "unknown"
        counts[str(severity)] += 1
        counts["total"] += 1
    return counts


def _scoped_runs(
    principal: Principal,
    *,
    product_id: str | None,
    component_id: str | None,
    release_id: str | None,
) -> tuple[QuerySet[Any], dict[str, Any]]:
    """Narrow the workspace's security runs to the requested scope.

    Each id is resolved first, so an unknown or out-of-workspace id raises a
    uniform not-found rather than silently matching nothing — otherwise a typo
    would return an all-zero report that an agent would relay as "no known
    vulnerabilities".
    """
    team = resolve_workspace(principal)
    require(principal, "workspace:read", team)
    runs = _security_runs(team)

    if release_id is not None:
        release_obj = _get_release(principal, release_id)
        sbom_ids = [artifact.sbom_id for artifact in release_obj.artifacts.all() if artifact.sbom_id]
        return runs.filter(sbom_id__in=sbom_ids), {"release_id": release_id}

    if component_id is not None:
        component = _lookup_component(principal, component_id)
        return runs.filter(sbom__component_id=component.id), {"component_id": component_id}

    if product_id is not None:
        product = _lookup_product(principal, product_id)
        return runs.filter(sbom__component__products__id=product.id), {"product_id": product_id}

    return runs, {"workspace": team.key}


def _present(row: dict[str, Any]) -> dict[str, Any]:
    """Shape one finding row for an agent.

    ``id``, ``title``, ``package`` and ``version`` originate in scanner output
    over supplier-supplied SBOM content, so each is truncated by ``untrusted``.
    """
    return serializers.compact(
        {
            "id": untrusted(row.get("id"), limit=128),
            "severity": row.get("severity"),
            "package": untrusted(row.get("package"), limit=512),
            "version": untrusted(row.get("version"), limit=128),
            "ecosystem": untrusted(row.get("ecosystem"), limit=64),
            "cvss_score": row.get("cvss_score"),
            "fixed_version": untrusted(row.get("fixed"), limit=128) or None,
            "suppressed": row.get("vex_suppressed") or None,
            "suppression_state": row.get("vex_state") or None,
            "component_id": row.get("component_id"),
            "component_name": row.get("component_name"),
            "sbom_id": row.get("sbom_id"),
            "providers": row.get("providers"),
        }
    )


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "get_vulnerability_summary", "workspace:read")
    async def get_vulnerability_summary(
        principal: Principal,
        product_id: str | None = None,
        component_id: str | None = None,
        release_id: str | None = None,
    ) -> dict[str, Any]:
        """Vulnerability severity counts, workspace-wide or narrowed to one scope.

        Pass at most one of `product_id`, `component_id` or `release_id`. With no
        filter, reports the whole workspace.

        Counts exclude findings the customer has dispositioned via VEX (reported
        separately as `suppressed`), and match what the sbomify dashboards show.
        """

        def query() -> dict[str, Any]:
            runs, scope = _scoped_runs(
                principal, product_id=product_id, component_id=component_id, release_id=release_id
            )
            rows, scanned = _rows_for(runs)
            return {
                "scope": scope,
                "severity_counts": _counts(rows),
                "suppressed": sum(1 for row in rows if row.get("vex_suppressed")),
                "sboms_scanned": len(scanned),
            }

        return await run_db(query)

    @mcp_tool(mcp, "list_vulnerabilities", "workspace:read")
    async def list_vulnerabilities(
        principal: Principal,
        product_id: str | None = None,
        component_id: str | None = None,
        release_id: str | None = None,
        severity: str | None = None,
        include_suppressed: bool = False,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """Individual vulnerability findings, worst first.

        `severity` filters to one of critical, high, medium, low, unknown.
        Findings the customer has dispositioned via VEX are excluded unless
        `include_suppressed` is set; when included they carry `suppressed: true`
        and the state that suppressed them.

        Each finding names the package and version it affects plus the component
        and SBOM it was found in, so it can be traced back to what ships it.
        """

        def query() -> dict[str, Any]:
            runs, _scope = _scoped_runs(
                principal, product_id=product_id, component_id=component_id, release_id=release_id
            )
            rows, _scanned = _rows_for(runs)

            if not include_suppressed:
                rows = [row for row in rows if not row.get("vex_suppressed")]
            if severity:
                wanted = severity.strip().lower()
                rows = [row for row in rows if row.get("severity") == wanted]

            safe_page, safe_size = clamp_page(page, page_size)
            start = (safe_page - 1) * safe_size
            return serializers.paginated(
                [_present(row) for row in rows[start : start + safe_size]],
                page=safe_page,
                page_size=safe_size,
                total=len(rows),
            )

        return await run_db(query)

    @mcp_tool(mcp, "get_release_risk_report", "release:read")
    async def get_release_risk_report(principal: Principal, release_id: str) -> dict[str, Any]:
        """One-call risk posture for a release.

        Combines the release, its tagged artifacts, vulnerability severity counts
        and compliance assessment status. Prefer this over calling `get_release`,
        `get_vulnerability_summary` and `get_assessments` separately — it is the
        intended answer to "how risky is this release?".
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.plugins.models import AssessmentRun
            from sbomify.apps.plugins.sdk.enums import AssessmentCategory

            release_obj = _get_release(principal, release_id)
            artifacts = list(release_obj.artifacts.select_related("sbom", "document").all())
            sbom_ids = [artifact.sbom_id for artifact in artifacts if artifact.sbom_id]

            rows, scanned = _rows_for(_security_runs(release_obj.product.team).filter(sbom_id__in=sbom_ids))

            compliance_runs = (
                AssessmentRun.objects.filter(sbom_id__in=sbom_ids)
                .exclude(category=AssessmentCategory.SECURITY.value)
                .order_by("sbom_id", "plugin_name", "-created_at")
            )
            compliance: dict[str, list[str]] = {}
            seen: set[tuple[str, str]] = set()
            for run in compliance_runs:
                key = (run.sbom_id, run.plugin_name)
                if key in seen:
                    continue
                seen.add(key)
                compliance.setdefault(run.plugin_name, []).append(run.status)

            return serializers.compact(
                {
                    "release": serializers.release(release_obj, detail=True),
                    "product": {"id": release_obj.product.id, "name": release_obj.product.name},
                    "artifact_counts": {
                        "sboms": len(sbom_ids),
                        "documents": sum(1 for a in artifacts if a.document_id),
                    },
                    "severity_counts": _counts(rows),
                    "suppressed": sum(1 for row in rows if row.get("vex_suppressed")),
                    "sboms_scanned": len(scanned),
                    "unscanned_sboms": len(set(sbom_ids) - scanned),
                    "compliance": {
                        plugin: {"runs": len(statuses), "statuses": sorted(set(statuses))}
                        for plugin, statuses in compliance.items()
                    },
                }
            )

        return await run_db(query)

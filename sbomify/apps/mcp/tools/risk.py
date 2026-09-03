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

from mcp.server.fastmcp.exceptions import ToolError

from .. import serializers
from ..auth import Principal, require
from ..limits import untrusted
from ._base import clamp_page, mcp_tool, resolve_workspace, run_db
from .catalog import _get_release, _lookup_component, _lookup_product, _lookup_release

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from mcp.server.fastmcp import FastMCP

# Mirrors utils.SEVERITY_RANK plus the no-severity bucket. Hand-written rather
# than derived so this module keeps its imports lazy; test_risk_semantics
# asserts the two stay in sync.
SEVERITIES = ("critical", "high", "medium", "low", "info", "unknown")


def _security_runs(
    team: Any,
    *,
    component_id: Any = None,
    product_id: Any = None,
    sbom_ids: list[Any] | None = None,
) -> QuerySet[Any]:
    """The latest completed security run per (SBOM, provider) in scope.

    Which SBOMs count mirrors the dashboards (``core.services.dashboard_page``):
    only the newest ``bom_type=sbom`` artifact per component — counting every
    historical version would report the same finding once per upload. A release
    scope passes ``sbom_ids`` instead, because a release is pinned to specific
    artifacts whether or not they are still the newest.

    Latest-per-provider is resolved in the database (``DISTINCT ON``), again
    like the dashboards — materializing the full history would fetch every
    superseded run's multi-MB ``result`` blob only to discard it.

    Completed only, like every dashboard consumer of these runs: a pending or
    failed run has no ``result``, so letting it win the newest-per-provider
    pick would make a mid-rescan SBOM read as scanned-and-clean.
    """
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunStatus
    from sbomify.apps.sboms.models import SBOM

    scope: Any
    if sbom_ids is None:
        sboms = SBOM.objects.filter(component__team=team, bom_type=SBOM.BomType.SBOM)
        if component_id is not None:
            sboms = sboms.filter(component_id=component_id)
        if product_id is not None:
            sboms = sboms.filter(component__products__id=product_id)
        scope = sboms.order_by("component_id", "-created_at").distinct("component_id").values("id")
    else:
        scope = sbom_ids

    return (
        AssessmentRun.objects.filter(
            sbom_id__in=scope,
            sbom__component__team=team,
            category=AssessmentCategory.SECURITY.value,
            status=RunStatus.COMPLETED.value,
        )
        .select_related("sbom", "sbom__component")
        .order_by("sbom_id", "plugin_name", "-created_at", "-id")
        .distinct("sbom_id", "plugin_name")
    )


def _release_sbom_ids(release_obj: Any) -> Any:
    """Ids of the release's tagged ``bom_type=sbom`` artifacts.

    The bom_type filter matches ``posture.build_release_vuln_posture``: a
    release also tags VEX rows (stored in the SBOM table), and counting those
    as SBOMs would report them forever "unscanned".
    """
    from sbomify.apps.sboms.models import SBOM

    return release_obj.artifacts.filter(sbom__isnull=False, sbom__bom_type=SBOM.BomType.SBOM).values_list(
        "sbom_id", flat=True
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
    from sbomify.apps.vulnerability_scanning.kev import kev_ids_for_serialization
    from sbomify.apps.vulnerability_scanning.utils import (
        extract_finding_rows,
        is_vulnerability,
        merge_findings_by_alias,
    )
    from sbomify.apps.vulnerability_scanning.vex import load_vex_suppressions

    rows: list[dict[str, Any]] = []
    scanned: set[str] = set()
    # One S3 fetch per component per call, like the dashboards' request-scoped
    # cache — several SBOMs usually share a component.
    vex_cache: dict[Any, list[dict[str, Any]]] = {}
    # Cached-only, warming in the background when cold — same source the
    # assessments panel badges known-exploited findings from.
    kev_ids = kev_ids_for_serialization()

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
        # The component's live VEX suppressions, like every dashboard caller: a
        # VEX uploaded after the scan must read as suppressed without a re-scan.
        statements = load_vex_suppressions(sbom.component_id, cache=vex_cache)
        for row in extract_finding_rows(merged, statements, kev_ids=kev_ids):
            row["sbom_id"] = sbom_id
            row["component_id"] = sbom.component_id
            row["component_name"] = sbom.component.name
            row["providers"] = providers
            rows.append(row)

    # extract_finding_rows sorts within one SBOM; re-sort the concatenation so
    # "worst first" holds across SBOMs too — otherwise page 1 of a multi-SBOM
    # scope is whichever SBOM's id sorts first, not the worst findings. Same
    # key as the per-SBOM sort: malicious packages lead (they carry no severity
    # to rank by), then severity, then CVSS descending.
    rows.sort(
        key=lambda row: (
            not row.get("malicious"),
            SEVERITIES.index(_severity_bucket(row)),
            -(row.get("cvss_score") or 0),
        )
    )
    return rows, scanned


def _severity_bucket(row: dict[str, Any]) -> str:
    """The severity bucket a row lands in; anything unrecognised is ``unknown``.

    Shared by the summary tally and the list filter so that a count read from
    `get_vulnerability_summary` is always reachable through
    `list_vulnerabilities(severity=...)` with the same name.
    """
    severity = row.get("severity")
    return severity if severity in SEVERITIES else "unknown"


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Severity tally over live (non-VEX-suppressed) findings."""
    counts = dict.fromkeys(("total", *SEVERITIES), 0)
    for row in rows:
        if row.get("vex_suppressed"):
            continue
        counts[_severity_bucket(row)] += 1
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
    if sum(1 for value in (product_id, component_id, release_id) if value is not None) > 1:
        # Silently honouring one and ignoring the rest would hand back numbers
        # for a scope the agent did not ask about, labelled plausibly enough to
        # be relayed as the answer.
        raise ToolError("Pass at most one of product_id, component_id or release_id.")

    team = resolve_workspace(principal)
    require(principal, "workspace:read", team)

    if release_id is not None:
        # Workspace-scoped lookup only: this tool's declared action is
        # workspace:read, which already covers every finding in the workspace —
        # demanding release:read for the narrowing would advertise-then-refuse
        # a token scoped to exactly the declared action.
        release_obj = _lookup_release(principal, release_id)
        sbom_ids = list(_release_sbom_ids(release_obj))
        return _security_runs(team, sbom_ids=sbom_ids), {"release_id": release_id}

    if component_id is not None:
        component = _lookup_component(principal, component_id)
        return _security_runs(team, component_id=component.id), {"component_id": component_id}

    if product_id is not None:
        product = _lookup_product(principal, product_id)
        return _security_runs(team, product_id=product.id), {"product_id": product_id}

    return _security_runs(team), {"workspace": team.key}


def _present(row: dict[str, Any]) -> dict[str, Any]:
    """Shape one finding row for an agent.

    ``id``, ``package``, ``version`` and ``ecosystem`` originate in scanner
    output over supplier-supplied SBOM content, so each is truncated by
    ``untrusted``.
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
            # The two flags the UI badges and ranks on. Malicious packages
            # (OpenSSF records) carry no severity, so without this marker they
            # would read as ignorable "unknown" findings; kev marks CISA
            # known-exploited CVEs.
            "malicious": row.get("malicious") or None,
            "known_exploited": row.get("kev") or None,
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

        `severity` filters to one of critical, high, medium, low, info, unknown.
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
                if wanted not in SEVERITIES:
                    # An unrecognised name ("moderate", "warning") must not
                    # read as an empty-but-valid result — the agent would
                    # relay "none found" for findings that exist under a
                    # bucket it did not guess.
                    raise ToolError(f"Unknown severity {severity!r}; expected one of: {', '.join(SEVERITIES)}.")
                rows = [row for row in rows if _severity_bucket(row) == wanted]

            safe_page, safe_size = clamp_page(page, page_size)
            start = (safe_page - 1) * safe_size
            return serializers.paginated(
                [_present(row) for row in rows[start : start + safe_size]],
                page=safe_page,
                page_size=safe_size,
                total=len(rows),
            )

        return await run_db(query)

    # also_requires workspace:read: the report folds in the vulnerability and
    # compliance posture that the sibling tools gate behind workspace:read —
    # release:read alone (a member of the `publish` preset, minted for CI
    # upload tokens) must not unlock the workspace's security posture.
    @mcp_tool(mcp, "get_release_risk_report", "release:read", also_requires=("workspace:read",))
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
            from sbomify.apps.sboms.models import SBOM

            release_obj = _get_release(principal, release_id)
            artifacts = list(release_obj.artifacts.select_related("sbom", "document").all())
            # Two scopes, split like the release surfaces split them. Security
            # scanning covers bom_type=sbom only (a tagged VEX or CBOM row can
            # never earn a security run, so counting one would report it
            # forever "unscanned" — posture.build_release_vuln_posture filters
            # the same way). Compliance keeps every SBOM-table artifact: the
            # crypto/PQC plugins are compliance-category and run on CBOMs.
            sbom_ids = [a.sbom_id for a in artifacts if a.sbom_id]
            scannable_ids = [a.sbom_id for a in artifacts if a.sbom_id and a.sbom.bom_type == SBOM.BomType.SBOM.value]

            rows, scanned = _rows_for(_security_runs(release_obj.product.team, sbom_ids=scannable_ids))

            # Latest per (sbom, plugin) resolved in the database; only
            # plugin_name and status are read, so the result blob stays deferred.
            compliance_runs = (
                AssessmentRun.objects.filter(sbom_id__in=sbom_ids)
                .exclude(category=AssessmentCategory.SECURITY.value)
                .order_by("sbom_id", "plugin_name", "-created_at", "-id")
                .distinct("sbom_id", "plugin_name")
                .defer("result")
            )
            compliance: dict[str, list[str]] = {}
            for run in compliance_runs:
                compliance.setdefault(run.plugin_name, []).append(run.status)

            return serializers.compact(
                {
                    "release": serializers.release(release_obj, detail=True),
                    "product": {"id": release_obj.product.id, "name": release_obj.product.name},
                    "artifact_counts": {
                        "sboms": len(scannable_ids),
                        "documents": sum(1 for a in artifacts if a.document_id),
                    },
                    "severity_counts": _counts(rows),
                    "suppressed": sum(1 for row in rows if row.get("vex_suppressed")),
                    "sboms_scanned": len(scanned),
                    "unscanned_sboms": len(set(scannable_ids) - scanned),
                    "compliance": {
                        plugin: {"runs": len(statuses), "statuses": sorted(set(statuses))}
                        for plugin, statuses in compliance.items()
                    },
                }
            )

        return await run_db(query)

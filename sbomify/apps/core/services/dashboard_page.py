"""The dashboard's security picture: the needs-attention digest.

The digest reuses the component drill-down's pipeline (provider-latest runs
merged by advisory alias, VEX-aware), so a finding reads identically on the
dashboard, the component page, and the product page — suppressed findings
never appear here.
"""

from __future__ import annotations

from typing import Any, cast

from django.core.cache import cache as django_cache

from sbomify.apps.core.models import Component
from sbomify.apps.sboms.models import SBOM

_CACHE_TTL_SECONDS = 60
_DIGEST_LIMIT = 3


#: How many ranked rows to fold before taking the digest's three.
#:
#: The fold is by alias and cannot go into SQL, so something has to bound what
#: it runs over. The database returns the worst rows first, and folding the top
#: few is enough: two rows can only merge into one, so the worst three survivors
#: are always inside the worst few candidates by a wide margin.
_DIGEST_CANDIDATES = 60


def _digest_rows(component_ids: list[str], component_names: dict[str, str]) -> list[dict[str, Any]]:
    """Worst non-suppressed findings across the given components.

    Read from the findings table rather than from scan results. The old shape
    loaded every current run's whole ``result`` for every component in the
    workspace, merged and extracted in Python, sorted the lot, and returned
    three rows. The work scaled with the workspace while the answer never grew.

    Ranking and bounding now happen in SQL. What stays in Python is the
    cross-provider fold, because it is by alias and transitive, and it runs over
    the ranked candidates rather than over everything.
    """
    from django.db.models import F, Value
    from django.db.models.functions import Coalesce

    from sbomify.apps.vulnerability_scanning.models import Finding

    # ``is_current`` is scoped per SBOM, not per component: it means the newest
    # run per (sbom, plugin). A component that has since uploaded a newer
    # artifact still has current rows against the superseded one, and the
    # dashboard must not resurface those, so the newest SBOM per component is
    # resolved first and the findings are narrowed to it.
    latest_sbom_ids = (
        SBOM.objects.filter(component_id__in=component_ids, bom_type=SBOM.BomType.SBOM)
        .order_by("component_id", "-created_at")
        .distinct("component_id")
        .values_list("id", flat=True)
    )

    candidates = (
        Finding.objects.filter(
            component_id__in=component_ids,
            sbom_id__in=latest_sbom_ids,
            # Rows accumulate per run, so one advisory seen by fifty scans is
            # fifty rows. Every reader has to narrow to the current ones.
            is_current=True,
            vex_suppressed=False,
        )
        .annotate(scanned_at=F("run__created_at"), sbom_version=F("sbom__version"))
        .order_by(
            # Malicious first, ahead of severity, for the reason the model
            # records: a malicious package carries no severity of its own, so
            # ranking on severity alone buries it in the unranked bucket below
            # every real CVE, and it is a remove-now decision rather than a
            # patch-later one. The old Python sort had the same gap; porting it
            # unchanged would have carried the gap across.
            F("malicious").desc(),
            "severity_rank",
            F("run__created_at").desc(),
            # The display rule is ``or 0``, so a missing score ties with an
            # explicit 0.0 rather than sorting above or below every score.
            Coalesce("cvss_score", Value(0.0)).desc(),
        )
        .values(
            "advisory_id",
            "aliases",
            "severity",
            "cvss_score",
            "package_name",
            "package_version",
            "ecosystem",
            "vex_state",
            "malicious",
            "component_id",
            "scanned_at",
            "sbom_version",
        )[:_DIGEST_CANDIDATES]
    )

    folded: list[dict[str, Any]] = []
    for row in _fold_by_alias(list(candidates))[:_DIGEST_LIMIT]:
        folded.append(
            {
                "id": row["advisory_id"],
                "severity": row["severity"],
                "cvss_score": row["cvss_score"],
                "package": row["package_name"],
                "version": row["package_version"],
                "ecosystem": row["ecosystem"],
                "vex_state": row["vex_state"],
                "malicious": row["malicious"],
                "component_id": row["component_id"],
                "component_name": component_names.get(row["component_id"], ""),
                "sbom_version": row["sbom_version"],
                "scanned_at": row["scanned_at"],
            }
        )
    return folded


def _fold_by_alias(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per advisory, however many ids the scanners reported it under.

    Transitive, which is the whole difficulty. OSV can report ``GHSA-a`` aliased
    to ``CVE-1``, Dependency Track can report ``CVE-1`` aliased to ``CVE-2``, and
    a third can report ``CVE-2`` alone. All three are one vulnerability, and no
    pair of them shares an id with the third. A single pass that claims ids as it
    goes folds the first two and then emits the third beside them, because by the
    time the bridging row arrives the earlier ones have already been written out.

    So the groups are built first and emitted afterwards. ``rows`` arrives in the
    order the database ranked it, and each group is represented by its earliest
    member, so folding never promotes a finding above one that outranks it.
    """
    group_of: dict[str, int] = {}
    groups: list[list[int]] = []

    for position, row in enumerate(rows):
        keys = {str(one).lower() for one in (row["advisory_id"], *(row.get("aliases") or [])) if one}
        joined = sorted({group_of[key] for key in keys if key in group_of})
        if not joined:
            groups.append([position])
            target = len(groups) - 1
        else:
            # This row bridges groups that had no id in common until now, so they
            # are one vulnerability after all and have to be merged rather than
            # left as separate entries.
            target = joined[0]
            groups[target].append(position)
            for other in joined[1:]:
                groups[target].extend(groups[other])
                groups[other] = []
            for key, index in list(group_of.items()):
                if index in joined[1:]:
                    group_of[key] = target
        for key in keys:
            group_of[key] = target

    return [rows[min(members)] for members in groups if members]


def get_first_component(team_id: int) -> Component | None:
    """Uncached on purpose: the digest cache may lag a just-created component,
    and the onboarding hero must reflect it immediately."""
    return Component.objects.filter(team_id=team_id).first()


def build_dashboard_context(team_id: int) -> dict[str, Any]:
    cache_key = f"dashboard-page:{team_id}"
    cached = django_cache.get(cache_key)
    if cached is not None:
        return cast("dict[str, Any]", cached)

    components = dict(Component.objects.filter(team_id=team_id).values_list("id", "name"))
    has_artifacts = SBOM.objects.filter(component__team_id=team_id).exists()

    context = {
        "is_first_visit": not has_artifacts,
        "needs_attention": _digest_rows(list(components), components) if has_artifacts else [],
    }
    django_cache.set(cache_key, context, _CACHE_TTL_SECONDS)
    return context

"""End-of-life transition for a product (CRA checklist 6.1).

``Product.end_of_support`` and ``end_of_life`` already existed and nothing
happened when they arrived. The dates were the easy half; these are the
obligations attached to them.

:func:`eol_readiness` reports what stands between the product and a defensible
EOL. Checklist 6.1.6 requires every known critical and high vulnerability
patched **or formally risk-accepted** before EOL, which is why this waited on
the risk-acceptance state: without it there was no way to distinguish
"unresolved" from "accepted deliberately".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

# Checklist 6.1.6 recommends twelve months' notice for enterprise products.
# A default rather than a constant: a workspace shipping consumer devices may
# reasonably choose less, and the figure belongs in the announcement either way.
DEFAULT_EOL_NOTICE_DAYS = 365


@dataclass
class EolReadiness:
    """Whether a product can reach EOL with the checklist satisfied."""

    product_id: str
    end_of_support: date | None = None
    end_of_life: date | None = None
    days_to_end_of_support: int | None = None
    days_to_end_of_life: int | None = None
    notice_given: bool = False
    unresolved_critical: list[dict[str, Any]] = field(default_factory=list)
    unresolved_high: list[dict[str, Any]] = field(default_factory=list)
    accepted_count: int = 0
    has_final_sbom: bool = False
    has_final_vex: bool = False

    @property
    def blocking_count(self) -> int:
        return len(self.unresolved_critical) + len(self.unresolved_high)

    @property
    def is_ready(self) -> bool:
        """6.1.6: every critical and high patched or formally risk-accepted,
        and a final SBOM to leave behind."""
        return self.blocking_count == 0 and self.has_final_sbom

    @property
    def problems(self) -> list[str]:
        problems: list[str] = []
        if self.unresolved_critical:
            problems.append(
                f"{len(self.unresolved_critical)} critical finding(s) neither patched nor risk-accepted "
                "(checklist 6.1.6)."
            )
        if self.unresolved_high:
            problems.append(
                f"{len(self.unresolved_high)} high finding(s) neither patched nor risk-accepted (checklist 6.1.6)."
            )
        if not self.has_final_sbom:
            problems.append(
                "No SBOM on the release chosen as final to publish (checklist 6.1.6). "
                "The newest versioned release is chosen, not the floating latest pointer."
            )
        return problems


def _days_between(target: date | None, today: date) -> int | None:
    return None if target is None else (target - today).days


def _final_release(product: Any) -> Any:
    """The release whose artifacts should be published as final.

    A real, versioned release in preference to the floating ``latest``, which
    re-targets as artifacts arrive: pinning "final" to a moving pointer would
    mean the final SBOM changed after the product stopped being supported.
    ``latest`` is the fallback only when the product never cut a versioned
    release, where publishing something beats publishing nothing.
    """
    from sbomify.apps.core.models import Release

    # Ordered the way Release itself is ordered: released_at first, created_at
    # only to break ties. A release row can be created before an earlier-dated
    # one is published, and sorting on created_at alone would then call the
    # wrong release final.
    releases = Release.objects.filter(product=product)
    newest = ("-released_at", "-created_at")
    return releases.filter(is_latest=False).order_by(*newest).first() or releases.order_by(*newest).first()


def eol_readiness(
    product: Any, *, today: date | None = None, notice_days: int = DEFAULT_EOL_NOTICE_DAYS
) -> EolReadiness:
    """What stands between this product and a defensible end of life.

    A finding counts as handled when it is resolved or carries a live formal
    risk acceptance. A *lapsed* acceptance does not count: an expired
    decision is exactly the thing the acceptance expiry exists to resurface,
    and letting it pass here would make the expiry decorative.
    """
    from sbomify.apps.plugins.models import VulnerabilityLifecycle
    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.vulnerability_scanning.triage import RISK_ACCEPTED_STATE, current_triage_index

    today = today or date.today()
    readiness = EolReadiness(
        product_id=str(product.id),
        end_of_support=product.end_of_support,
        end_of_life=product.end_of_life,
        days_to_end_of_support=_days_between(product.end_of_support, today),
        days_to_end_of_life=_days_between(product.end_of_life, today),
    )
    if readiness.days_to_end_of_life is not None:
        readiness.notice_given = readiness.days_to_end_of_life >= notice_days

    components = list(product.components.all())
    if not components:
        return readiness

    # Live acceptances keyed by (component, advisory id). A triage decision is
    # recorded against one component, so a single set of advisory ids would let
    # an acceptance on component A clear the same advisory on component B — the
    # readiness check would then report fewer blockers than there are, which is
    # the direction that matters here.
    accepted: set[tuple[str, str]] = set()
    for component in components:
        for statement in current_triage_index(component).values():
            if statement.get("state") != RISK_ACCEPTED_STATE:
                continue
            raw = statement.get("accepted_until")
            try:
                if raw and date.fromisoformat(str(raw)) >= today:
                    accepted.add((str(component.id), (statement.get("id") or "").lower()))
            except ValueError:
                continue
    readiness.accepted_count = len(accepted)

    open_rows = VulnerabilityLifecycle.objects.filter(
        component__in=components, resolved_at__isnull=True, severity__in=("critical", "high")
    ).only("advisory_id", "severity", "component_id", "first_seen_at")
    for row in open_rows:
        if (str(row.component_id), row.advisory_id.lower()) in accepted:
            continue
        entry = {
            "advisory_id": row.advisory_id,
            "component_id": str(row.component_id),
            "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        }
        if row.severity == "critical":
            readiness.unresolved_critical.append(entry)
        else:
            readiness.unresolved_high.append(entry)

    final_release = _final_release(product)
    if final_release is not None:
        types = set(SBOM.objects.filter(releaseartifact__release=final_release).values_list("bom_type", flat=True))
        readiness.has_final_sbom = SBOM.BomType.SBOM in types
        readiness.has_final_vex = SBOM.BomType.VEX in types
    return readiness

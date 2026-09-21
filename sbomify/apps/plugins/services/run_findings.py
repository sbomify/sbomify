"""One page of a single assessment run's findings.

The run card on the artifact page renders its header from ``result.summary``,
which is a handful of integers however large the scan was. The findings list is
the part that grows with the SBOM, and building every finding of every plugin
for a page of collapsed accordions is what took that page past the gateway
timeout. This resolves the list for one run, one page at a time, when a reader
opens the card.

Read-time flags are stamped here rather than stored, the same way the
assessments endpoint does it, so a page of findings carries the same KEV, EUVD
and malicious marks wherever it is read from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.vulnerability_scanning.services.finding_browse import (
    browse_finding_rows,
)

#: The card's filter controls. Its own endpoint, so nothing would collide with
#: the component panel's ``vuln_`` parameters, but naming them keeps a link that
#: carries both readable.
PARAM_PREFIX = "run_"

#: Findings per page in the card. The component panel shows five because it sits
#: in a page full of other cards; this one owns its accordion, so it shows more.
PAGE_SIZE = 25


@dataclass(frozen=True)
class RunFindingsPage:
    """One page of a run's findings, plus what the template needs around it."""

    run: Any
    sbom: Any
    is_security: bool
    findings: list[dict[str, Any]]
    page: int
    page_count: int
    has_prev: bool
    has_next: bool
    #: Everything the toolbar renders: the active query, the option lists the
    #: filters offer, and the totals the counts read.
    panel: dict[str, Any]


def _filterable(finding: dict[str, Any]) -> dict[str, Any]:
    """A finding with the flat keys the browse layer reads added to it.

    The card renders raw findings, which carry the references, CVSS, EPSS,
    malicious flag and description its template needs. The browse layer reads a
    flatter shape: ``package``, ``ecosystem``, ``vex_state``, ``vex_suppressed``.
    Rather than convert the card to that shape and lose everything the flat one
    does not carry, the few keys are added alongside. None of them collide with
    a name the template already reads.
    """
    from sbomify.apps.vulnerability_scanning.vex import SUPPRESSED_STATES

    component = finding.get("component") or {}
    state = finding.get("analysis_state") or ""
    return {
        **finding,
        "package": component.get("name") or "",
        "ecosystem": component.get("ecosystem") or "",
        "vex_state": state,
        "vex_suppressed": state in SUPPRESSED_STATES,
    }


def build_run_findings_page(request: Any, run_id: str, params: Any = None) -> ServiceResult[RunFindingsPage]:
    """Resolve a page of findings for a run the caller may read.

    A run the caller may not read and a run that does not exist give the same
    404: for an assessment this reader has no business with, confirming one
    exists at that id is itself an answer.

    ``params`` is the request's query dict: the page, and the search and filters
    the toolbar posts back.
    """
    from sbomify.apps.plugins.apis import _readable_sbom, _result_with_kev
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.templatetags.plugins_extras import vulnerability_findings
    from sbomify.apps.vulnerability_scanning.euvd import euvd_ids_for_serialization
    from sbomify.apps.vulnerability_scanning.kev import kev_ids_for_serialization
    from sbomify.apps.vulnerability_scanning.services.finding_browse import parse_finding_query

    missing: ServiceResult[RunFindingsPage] = ServiceResult.failure("Assessment run not found", status_code=404)
    try:
        # The id reaches this from a template, so a value that is not a UUID at
        # all is a 404 rather than the ValidationError the field lookup raises.
        UUID(str(run_id))
    except ValueError:
        return missing

    run = AssessmentRun.objects.filter(id=run_id).first()
    if run is None:
        return missing
    sbom = _readable_sbom(request, str(run.sbom_id))
    if sbom is None:
        return missing

    is_security = run.category == "security"
    kev_ids = kev_ids_for_serialization() if is_security else frozenset()
    euvd_ids = euvd_ids_for_serialization() if is_security else frozenset()
    result = _result_with_kev(run, kev_ids, euvd_ids)
    findings = result.get("findings") if isinstance(result, dict) else None
    if not isinstance(findings, list):
        findings = []
    if is_security:
        # Scanner status markers ride the same array and are not
        # vulnerabilities, the filter the eager list used to apply.
        findings = vulnerability_findings(findings)

    query = parse_finding_query(params if params is not None else {}, prefix=PARAM_PREFIX, default_per_page=PAGE_SIZE)
    panel = browse_finding_rows([_filterable(f) for f in findings if isinstance(f, dict)], query)
    return ServiceResult.success(
        RunFindingsPage(
            run=run,
            sbom=sbom,
            is_security=is_security,
            findings=panel["rows"],
            page=panel["page"],
            page_count=panel["page_count"],
            has_prev=panel["has_prev"],
            has_next=panel["has_next"],
            panel=panel,
        )
    )

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

from django.core.paginator import Paginator

from sbomify.apps.core.services.results import ServiceResult

#: Findings per page. Matches the vulnerabilities panel, so a reader moving
#: between the two pages at the same rate.
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


def build_run_findings_page(request: Any, run_id: str, page: Any = None) -> ServiceResult[RunFindingsPage]:
    """Resolve a page of findings for a run the caller may read.

    A run the caller may not read and a run that does not exist give the same
    404: for an assessment this reader has no business with, confirming one
    exists at that id is itself an answer.
    """
    from sbomify.apps.plugins.apis import _readable_sbom, _result_with_kev
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.templatetags.plugins_extras import vulnerability_findings
    from sbomify.apps.vulnerability_scanning.euvd import euvd_ids_for_serialization
    from sbomify.apps.vulnerability_scanning.kev import kev_ids_for_serialization

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

    paginator = Paginator(findings, PAGE_SIZE)
    current = paginator.get_page(page)
    return ServiceResult.success(
        RunFindingsPage(
            run=run,
            sbom=sbom,
            is_security=is_security,
            findings=list(current.object_list),
            page=current.number,
            page_count=paginator.num_pages,
            has_prev=current.has_previous(),
            has_next=current.has_next(),
        )
    )

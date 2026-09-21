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

Only the page leaves Postgres whole. Resolving the stored result to render
twenty-five rows meant de-TOASTing and parsing every finding the scan produced,
which is most of what opening a card costs: at 4,075 findings the blob is about
12 MB uncompressed and 22.7 ms of the 33 ms the page takes. Filtering and the
toolbar's counts read seven keys per finding and never touch a title,
description or reference list, so those seven come back as a flat projection and
the rest stays in the database until the page is known.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import connection

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

    Both the projection and the page pass through here, which is why the alias
    list is normalised here rather than in either of them.
    """
    from sbomify.apps.vulnerability_scanning.vex import SUPPRESSED_STATES

    component = finding.get("component") or {}
    state = finding.get("analysis_state") or ""
    # Only the projection gets aliases as a text array from SQL; the page gets
    # whatever was stored. The template iterates them for the badge list and
    # joins them into the triage payload, so a stored string would render one
    # badge per character and submit the same nonsense to the triage API.
    aliases = finding.get("aliases")
    return {
        **finding,
        "aliases": [str(alias) for alias in aliases] if isinstance(aliases, list) else [],
        "package": component.get("name") or "",
        "ecosystem": component.get("ecosystem") or "",
        "vex_state": state,
        "vex_suppressed": state in SUPPRESSED_STATES,
    }


#: Every finding in the run, carrying only what a filter or a count reads.
#:
#: ``_matches`` reads the severity, the VEX state, the KEV mark and the search
#: haystack; the haystack is the advisory id, its aliases, the package and its
#: ecosystem. The option lists and the KEV and suppressed totals read the same
#: keys again. Nothing in that set is large, and nothing outside it is needed
#: until a row renders, so the projection stops there.
#:
#: Ordinality carries the position in the stored array, which is how a page of
#: these maps back to the findings themselves. Everything is read out as a text
#: scalar or a text array: a raw cursor hands a jsonb column back as the JSON
#: source, so anything left as jsonb here would arrive as a string and quietly
#: iterate as its characters.
_PROJECTION_SQL = """
    SELECT t.ord - 1,
           t.finding ->> 'id',
           t.finding ->> 'status',
           CASE WHEN jsonb_typeof(t.finding -> 'aliases') = 'array'
                THEN ARRAY(SELECT jsonb_array_elements_text(t.finding -> 'aliases'))
                ELSE ARRAY[]::text[] END,
           t.finding ->> 'severity',
           t.finding ->> 'analysis_state',
           t.finding -> 'component' ->> 'name',
           t.finding -> 'component' ->> 'ecosystem'
    FROM {table} run
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(run.result -> 'findings') = 'array'
             THEN run.result -> 'findings'
             ELSE '[]'::jsonb END
    ) WITH ORDINALITY AS t(finding, ord)
    WHERE run.id = %s AND jsonb_typeof(t.finding) = 'object'
    ORDER BY t.ord
"""

#: The findings themselves, for the handful of positions a page renders. Guarded
#: the same way as the projection: a run rescanned between the two queries comes
#: back empty rather than raising, and a stored array holding anything that is
#: not an object skips it rather than handing the template a string.
_PAGE_SQL = """
    SELECT t.ord - 1, t.finding
    FROM {table} run
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(run.result -> 'findings') = 'array'
             THEN run.result -> 'findings'
             ELSE '[]'::jsonb END
    ) WITH ORDINALITY AS t(finding, ord)
    WHERE run.id = %s AND t.ord - 1 = ANY(%s) AND jsonb_typeof(t.finding) = 'object'
"""

#: Set on a projected finding, never on a stored one: where it sits in the
#: array. Leading underscore because it is plumbing between the two queries
#: above and not something a row carries onwards.
_POSITION = "_position"


def _projected_findings(run_id: UUID, table: str) -> list[dict[str, Any]]:
    """One dict per stored finding, holding the projection and its position.

    ``table`` is formatted into the statement because a table name cannot be a
    bound parameter. It comes from the model's own ``_meta``, never from the
    request.
    """
    with connection.cursor() as cursor:
        cursor.execute(_PROJECTION_SQL.format(table=table), [str(run_id)])
        rows = cursor.fetchall()

    return [
        {
            _POSITION: position,
            "id": advisory_id or "",
            "status": status,
            "aliases": aliases or [],
            "severity": severity,
            "analysis_state": state,
            "component": {"name": name, "ecosystem": ecosystem},
        }
        for position, advisory_id, status, aliases, severity, state, name, ecosystem in rows
    ]


def _findings_at(
    run_id: UUID,
    table: str,
    positions: list[int],
    kev_ids: frozenset[str],
    euvd_ids: frozenset[str],
    is_security: bool,
) -> list[dict[str, Any]]:
    """The full findings at ``positions``, stamped and in that order.

    The order is taken from ``positions`` rather than from the array, so this
    keeps rendering the page the browse layer chose even if that layer ever
    starts sorting.

    All three read-time marks are security-only, which is where the assessments
    endpoint puts them too: a compliance check reports a standard's field, not
    a package, so there is nothing for KEV or a malicious-package database to
    match against.
    """
    from sbomify.apps.vulnerability_scanning.kev import stamp_exploited
    from sbomify.apps.vulnerability_scanning.malicious import stamp_malicious

    if not positions:
        return []

    with connection.cursor() as cursor:
        cursor.execute(_PAGE_SQL.format(table=table), [str(run_id), positions])
        # json.loads because this one is a jsonb column read through a raw
        # cursor, which arrives as the JSON source rather than as a dict. The
        # statement returns objects only, so there is nothing else to get back.
        by_position = {position: json.loads(finding) for position, finding in cursor.fetchall()}

    findings = [by_position[position] for position in positions if position in by_position]
    if is_security:
        findings, _ = stamp_malicious(stamp_exploited(findings, kev_ids, euvd_ids))
    return [_filterable(finding) for finding in findings]


def build_run_findings_page(request: Any, run_id: str, params: Any = None) -> ServiceResult[RunFindingsPage]:
    """Resolve a page of findings for a run the caller may read.

    A run the caller may not read and a run that does not exist give the same
    404: for an assessment this reader has no business with, confirming one
    exists at that id is itself an answer.

    ``params`` is the request's query dict: the page, and the search and filters
    the toolbar posts back.
    """
    from sbomify.apps.plugins.apis import _readable_sbom
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.templatetags.plugins_extras import vulnerability_findings
    from sbomify.apps.vulnerability_scanning.euvd import euvd_ids_for_serialization
    from sbomify.apps.vulnerability_scanning.kev import kev_ids_for_serialization, stamp_exploited
    from sbomify.apps.vulnerability_scanning.services.finding_browse import parse_finding_query

    missing: ServiceResult[RunFindingsPage] = ServiceResult.failure("Assessment run not found", status_code=404)
    try:
        # The id reaches this from a template, so a value that is not a UUID at
        # all is a 404 rather than the ValidationError the field lookup raises.
        UUID(str(run_id))
    except ValueError:
        return missing

    # Deferred because the two queries below read it in pieces, and because the
    # card's template asks this object for its id and its category only. Loading
    # it here would put the whole blob back on the request.
    run = AssessmentRun.objects.defer("result").filter(id=run_id).first()
    if run is None:
        return missing
    sbom = _readable_sbom(request, str(run.sbom_id))
    if sbom is None:
        return missing

    is_security = run.category == "security"
    kev_ids = kev_ids_for_serialization() if is_security else frozenset()
    euvd_ids = euvd_ids_for_serialization() if is_security else frozenset()

    table = AssessmentRun._meta.db_table
    findings = _projected_findings(run.id, table)
    if is_security:
        # Scanner status markers ride the same array and are not
        # vulnerabilities, the filter the eager list used to apply. Both signals
        # it reads, the id prefix and the status, are in the projection.
        findings = vulnerability_findings(findings)
        # The KEV filter and the KEV total are both counted over the whole run,
        # so the mark is stamped here as well as on the page. Its two inputs,
        # the advisory id and its aliases, are in the projection too.
        findings = stamp_exploited(findings, kev_ids, euvd_ids)

    query = parse_finding_query(params if params is not None else {}, prefix=PARAM_PREFIX, default_per_page=PAGE_SIZE)
    panel = browse_finding_rows([_filterable(finding) for finding in findings], query)
    positions = [row[_POSITION] for row in panel["rows"]]
    panel["rows"] = _findings_at(run.id, table, positions, kev_ids, euvd_ids, is_security)
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

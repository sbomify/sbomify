"""One artifact's compliance checks, aggregated by the SBOM requirement they test.

Every compliance plugin checks much the same SBOM fields under its own name:
NTIA's ``sbom_author`` is BSI's ``sbom_creator``, CISA's ``software_producer``
is NTIA's ``supplier_name``. Listed per plugin, one missing author reads as four
separate failures. Grouped by requirement it reads as what it is: one gap in
the artifact, and the standards it holds back. That is the matrix the artifact
page shows, with a column per standard and a row per requirement.

A finding joins a requirement through the ``element`` its plugin records in
``metadata``. A finding with no element, or one no other standard shares, is
its own row under its plugin's title, so nothing a plugin reports is dropped.

Security scans are not part of this: a vulnerability is not a requirement an
artifact meets, and they keep their own rows and triage below the matrix.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from django.db import connection

from sbomify.apps.core.services.results import ServiceResult

#: Requirement key -> the label a reader sees.
REQUIREMENTS: dict[str, str] = {
    "sbom_author": "SBOM author",
    "supplier": "Supplier",
    "component_name": "Component name",
    "component_version": "Component version",
    "identifiers": "Unique identifiers",
    "dependencies": "Dependency relationships",
    "timestamp": "Timestamp",
    "hashes": "Component hashes",
    "licenses": "Licenses",
    "tool": "Generating tool",
    "generation_context": "Generation context",
    "sbom_format": "SBOM format",
}

#: Each plugin's element name -> the requirement it tests.
ELEMENTS: dict[str, str] = {
    "sbom_author": "sbom_author",
    "sbom_creator": "sbom_author",
    "supplier_name": "supplier",
    "software_producer": "supplier",
    "component_creator": "supplier",
    "component_producer": "supplier",
    "component_name": "component_name",
    "version": "component_version",
    "component_version": "component_version",
    "unique_identifiers": "identifiers",
    "software_identifiers": "identifiers",
    "component_identifiers": "identifiers",
    "dependency_relationship": "dependencies",
    "dependencies": "dependencies",
    "component_dependency_relationship": "dependencies",
    "timestamp": "timestamp",
    "sbom_timestamp": "timestamp",
    "component_hash": "hashes",
    "hash_value": "hashes",
    "component_hash_value": "hashes",
    "license": "licenses",
    "component_license": "licenses",
    "distribution_licences": "licenses",
    "original_licences": "licenses",
    "tool_name": "tool",
    "sbom_tool_name": "tool",
    "generation_context": "generation_context",
    "sbom_generation_context": "generation_context",
    "sbom_format": "sbom_format",
    "sbom_data_format_name": "sbom_format",
}

#: Column headings. A full plugin name does not fit over a column of icons.
SHORT_NAMES: dict[str, str] = {
    "ntia-minimum-elements-2021": "NTIA",
    "cisa-minimum-elements-2025": "CISA 2025",
    "cisa-minimum-elements-2026": "CISA 2026",
    "bsi-tr03183-v2.1-compliance": "BSI TR-03183",
    "fda-medical-device-2025": "FDA",
    "openchain-telco-1.1": "OpenChain",
    "sbom-verification": "Verification",
    "checksum": "Checksum",
}

#: Worst first. A requirement takes the worst outcome any standard gave it.
_RANK = {"error": 0, "fail": 0, "warning": 1, "info": 2, "pass": 3}  # nosec B105 - check outcomes, not credentials
_NOT_MET = ("fail", "error", "warning")

_SQL = """
    SELECT run.id, t.ord,
           t.finding ->> 'id',
           t.finding ->> 'status',
           COALESCE(NULLIF(t.finding ->> 'title', ''), t.finding ->> 'id'),
           t.finding -> 'metadata' ->> 'element',
           CASE WHEN t.finding ->> 'status' IN ('fail', 'error', 'warning')
                THEN t.finding ->> 'description' END,
           CASE WHEN t.finding ->> 'status' IN ('fail', 'error', 'warning')
                THEN t.finding ->> 'remediation' END
    FROM {table} run
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(run.result -> 'findings') = 'array'
             THEN run.result -> 'findings'
             ELSE '[]'::jsonb END
    ) WITH ORDINALITY AS t(finding, ord)
    WHERE run.id = ANY(%s::uuid[]) AND jsonb_typeof(t.finding) = 'object'
    ORDER BY t.ord
"""


@dataclass
class Standard:
    """A column: one compliance run and its score."""

    run: dict[str, Any]
    label: str
    name: str
    passed: int = 0
    total: int = 0
    issues: int = 0
    state: str = "scored"  # scored, skipped, failed, pending


@dataclass
class Requirement:
    """A row: one SBOM requirement and every standard's verdict on it."""

    key: str
    label: str
    status: str = "pass"
    cells: dict[str, str] = field(default_factory=dict)
    notes: list[dict[str, Any]] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    #: The verdicts in column order, "" where a standard does not check it.
    row: list[str] = field(default_factory=list)
    #: The column labels of the standards it holds back, for a phone, where
    #: the columns themselves do not fit.
    held_back: list[str] = field(default_factory=list)

    @property
    def standards_not_met(self) -> int:
        return sum(status in _NOT_MET for status in self.cells.values())


def _sentence_case(title: str) -> str:
    """ "Archive Property" as "Archive property", so every row label reads alike.

    Only a word written in title case is lowered, and never the first: an
    acronym (SBOM, URI, CLE) keeps its capitals.
    """
    words = re.split(r"([ -])", title)
    return "".join(
        word.lower() if index and len(word) > 1 and word[0].isupper() and word[1:].islower() else word
        for index, word in enumerate(words)
    )


def _worst(a: str, b: str) -> str:
    return a if _RANK.get(a, 2) <= _RANK.get(b, 2) else b


def _run_state(run: dict[str, Any]) -> str:
    if run.get("status") in ("pending", "running"):
        return "pending"
    if run.get("status") == "failed" or not run.get("result"):
        return "failed"
    if (run["result"].get("metadata") or {}).get("skipped"):
        return "skipped"
    return "scored"


def build_requirements(runs: list[dict[str, Any]]) -> ServiceResult[dict[str, Any]]:
    """The matrix for an artifact's latest runs, as the page's run dicts carry them."""
    from sbomify.apps.plugins.models import AssessmentRun

    standards = [
        Standard(
            run=run,
            label=SHORT_NAMES.get(run["plugin_name"]) or run.get("plugin_display_name") or run["plugin_name"],
            name=run.get("plugin_display_name") or run["plugin_name"],
            state=_run_state(run),
        )
        for run in runs
        if run.get("category") != "security"
    ]
    standards.sort(key=lambda standard: standard.label.casefold())
    has_scans = any(run.get("category") == "security" for run in runs)
    scored = {str(standard.run["id"]): standard for standard in standards if standard.state == "scored"}
    if not scored:
        return ServiceResult.success(
            {
                "columns": [],
                "sources": standards,
                "has_scans": has_scans,
                "requirements": [],
                "to_fix": 0,
                "to_review": 0,
                "met": 0,
            }
        )

    with connection.cursor() as cursor:
        cursor.execute(_SQL.format(table=AssessmentRun._meta.db_table), [list(scored)])
        rows = cursor.fetchall()

    requirements: dict[str, Requirement] = {}
    for run_id, _position, finding_id, status, title, element, description, remediation in rows:
        standard = scored[str(run_id)]
        status = status or "info"
        key = ELEMENTS.get(element or "") or f"{standard.run['plugin_name']}:{element or finding_id}"
        requirement = requirements.setdefault(
            key, Requirement(key=key, label=REQUIREMENTS.get(key) or _sentence_case(title))
        )
        plugin = standard.run["plugin_name"]
        requirement.cells[plugin] = _worst(requirement.cells.get(plugin, "pass"), status)
        requirement.status = _worst(requirement.status, status)
        standard.total += 1
        standard.passed += status == "pass"
        standard.issues += status in ("fail", "error")
        if status in _NOT_MET:
            requirement.notes.append(
                {
                    "plugin": plugin,
                    "standard": standard.name,
                    "status": status,
                    "title": title,
                    "description": description or "",
                }
            )
            if remediation and remediation not in requirement.fixes:
                requirement.fixes.append(remediation)

    columns = list(scored.values())
    order = {column.run["plugin_name"]: index for index, column in enumerate(columns)}
    for requirement in requirements.values():
        requirement.row = [requirement.cells.get(column.run["plugin_name"], "") for column in columns]
        # Under the columns they explain, in the same left-to-right order.
        requirement.notes.sort(key=lambda note: order[note["plugin"]])
        requirement.held_back = [
            column.label for column in columns if requirement.cells.get(column.run["plugin_name"]) in _NOT_MET
        ]
    ordered = sorted(
        requirements.values(),
        key=lambda requirement: (_RANK.get(requirement.status, 2), -requirement.standards_not_met, requirement.label),
    )
    return ServiceResult.success(
        {
            "columns": columns,
            "sources": standards,
            "has_scans": has_scans,
            "standards_met": sum(not column.issues for column in columns),
            "requirements": ordered,
            "to_fix": sum(requirement.status in ("fail", "error") for requirement in ordered),
            "to_review": sum(requirement.status == "warning" for requirement in ordered),
            "met": sum(requirement.status not in _NOT_MET for requirement in ordered),
        }
    )

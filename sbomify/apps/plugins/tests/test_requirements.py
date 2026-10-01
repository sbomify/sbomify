"""Aggregating an artifact's compliance checks by the requirement they test."""

import pytest

from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.services.requirements import build_requirements


def _finding(element: str | None, title: str, status: str, **extra: str) -> dict:
    finding = {"id": f"{title}-{status}", "title": title, "status": status, "description": "", **extra}
    if element:
        finding["metadata"] = {"element": element}
    return finding


def _run(sbom, plugin_name: str, findings: list[dict], category: str = "compliance", **result) -> dict:
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin_name,
        plugin_version="1.0",
        plugin_config_hash="test",
        category=category,
        status="completed",
        run_reason="on_upload",
        result={"findings": findings, "summary": {}, **result},
    )
    return {
        "id": str(run.id),
        "plugin_name": plugin_name,
        "plugin_display_name": plugin_name.upper(),
        "category": category,
        "status": "completed",
        "result": run.result,
    }


@pytest.mark.django_db
def test_one_gap_reads_as_one_requirement_across_standards(sample_sbom):
    runs = [
        _run(
            sample_sbom,
            "ntia-minimum-elements-2021",
            [
                _finding("sbom_author", "SBOM Author", "fail", remediation="Add an author."),
                _finding("component_name", "Component Name", "pass"),
            ],
        ),
        _run(
            sample_sbom,
            "bsi-tr03183-v2.1-compliance",
            [
                _finding("sbom_creator", "SBOM Creator", "fail", remediation="Add an author."),
                _finding("component_name", "Component Name", "pass"),
            ],
        ),
    ]
    matrix = build_requirements(runs).value

    assert [column.label for column in matrix["columns"]] == ["BSI TR-03183", "NTIA"]
    author, name = matrix["requirements"]
    assert (author.label, author.status, author.row) == ("SBOM author", "fail", ["fail", "fail"])
    assert author.fixes == ["Add an author."]
    assert author.held_back == ["BSI TR-03183", "NTIA"]
    assert [note["standard"] for note in author.notes] == ["BSI-TR03183-V2.1-COMPLIANCE", "NTIA-MINIMUM-ELEMENTS-2021"]
    assert (name.label, name.status) == ("Component name", "pass")
    assert (matrix["to_fix"], matrix["met"], matrix["standards_met"]) == (1, 1, 0)


@pytest.mark.django_db
def test_a_check_no_other_standard_shares_keeps_its_own_row(sample_sbom):
    runs = [
        _run(sample_sbom, "bsi-tr03183-v2.1-compliance", [_finding("archive_property", "Archive Property", "warning")]),
        _run(sample_sbom, "checksum", [_finding(None, "Integrity Verified", "pass")]),
    ]
    matrix = build_requirements(runs).value

    labels = {requirement.label: requirement.row for requirement in matrix["requirements"]}
    # Title case from the plugin is brought into line with every other row.
    assert labels == {"Archive property": ["warning", ""], "Integrity verified": ["", "pass"]}
    assert matrix["to_review"] == 1


@pytest.mark.django_db
def test_scans_and_skipped_runs_stay_out_of_the_matrix(sample_sbom):
    runs = [
        _run(sample_sbom, "osv", [_finding(None, "CVE-2026-0001", "fail")], category="security"),
        _run(
            sample_sbom,
            "ntia-minimum-elements-2021",
            [_finding(None, "Format not supported", "info")],
            metadata={"skipped": True},
        ),
    ]
    matrix = build_requirements(runs).value

    assert matrix["columns"] == []
    assert matrix["requirements"] == []
    assert matrix["has_scans"] is True
    assert [source.state for source in matrix["sources"]] == ["skipped"]


@pytest.mark.django_db
def test_the_worst_outcome_wins_within_one_standard(sample_sbom):
    runs = [
        _run(
            sample_sbom,
            "bsi-tr03183-v2.1-compliance",
            [
                _finding("distribution_licences", "Distribution Licences", "pass"),
                _finding("original_licences", "Original Licences", "fail"),
            ],
        )
    ]
    (licenses,) = build_requirements(runs).value["requirements"]
    assert (licenses.label, licenses.row) == ("Licenses", ["fail"])

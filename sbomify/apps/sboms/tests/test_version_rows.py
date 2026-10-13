"""The component card answers once per version, not once per file."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from sbomify.apps.core.models import Component
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk.enums import RunReason, RunStatus
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.services.version_rows import VERSION_LIMIT, build_version_rows
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db

NOW = timezone.now()


def finding(advisory: str, severity: str, package: str = "openssl", aliases: list[str] | None = None) -> dict:
    return {
        "id": advisory,
        "aliases": aliases or [],
        "severity": severity,
        "component": {"name": package, "version": "1.0"},
    }


def scan(*findings: dict) -> dict[str, Any]:
    return {"summary": {"total_findings": len(findings)}, "findings": list(findings), "metadata": {}}


SKIPPED = {"summary": {"total_findings": 0}, "findings": [], "metadata": {"skipped": True}}


@pytest.fixture
def component(sample_team_with_owner_member: Member) -> Component:
    return Component.objects.create(name="Container", team=sample_team_with_owner_member.team)


def artifact(
    component: Component,
    version: str,
    *,
    age: int,
    file_format: str = "cyclonedx",
    bom_type: str = "sbom",
    plugins: list[dict] | None = None,
    scans: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """One table item as list_component_sboms returns it, backed by real runs."""
    sbom = SBOM.objects.create(
        name=f"{version}-{file_format}-{bom_type}",
        component=component,
        version=version,
        format=file_format,
        format_version="1.6",
        bom_type=bom_type,
    )
    for plugin_name, result in (scans or {}).items():
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name=plugin_name,
            plugin_version="1",
            plugin_config_hash="h",
            run_reason=RunReason.ON_UPLOAD,
            category="security",
            status=RunStatus.COMPLETED.value,
            result=result,
        )
    return {
        "sbom": {
            "id": sbom.id,
            "name": sbom.name,
            "version": version,
            "format": file_format,
            "format_version": "1.6",
            "bom_type": bom_type,
            "created_at": NOW - timedelta(days=age),
        },
        "assessments": {"plugins": plugins or []},
    }


def check(name: str, status: str, category: str = "compliance") -> dict[str, str]:
    return {"name": name.lower(), "display_name": name, "status": status, "category": category}


def test_one_row_per_version_newest_first_with_every_file_downloadable(component: Component) -> None:
    items = [
        artifact(component, "1.0", age=3),
        artifact(component, "2.0", age=1, file_format="spdx"),
        artifact(component, "2.0", age=1, file_format="cyclonedx"),
        artifact(component, "2.0", age=1, bom_type="vex"),
    ]

    rows = build_version_rows(component.id, items)

    assert [row["version"] for row in rows] == ["2.0", "1.0"]
    assert sorted(file["label"] for file in rows[0]["downloads"]) == [
        "CycloneDX 1.6",
        "SPDX 1.6",
        "VEX (CycloneDX 1.6)",
    ]
    assert rows[0]["files"] == "SPDX 1.6 · CycloneDX 1.6 · VEX"


def test_formats_of_one_version_merge_into_one_answer(component: Component) -> None:
    """Two scanners reading two files report the same CVE twice; the row counts it once."""
    items = [
        artifact(
            component,
            "2.0",
            age=1,
            file_format="spdx",
            scans={"osv": scan(finding("GHSA-1", "critical", aliases=["CVE-1"]), finding("CVE-2", "high"))},
        ),
        artifact(component, "2.0", age=1, scans={"dependency-track": scan(finding("CVE-1", "critical"))}),
    ]

    (row,) = build_version_rows(component.id, items)

    assert row["vulnerabilities"] == {"state": "open", "critical": 1, "high": 1, "other": 0, "new": None}


def test_new_counts_only_what_the_previous_version_did_not_have(component: Component) -> None:
    items = [
        artifact(component, "1.0", age=2, scans={"osv": scan(finding("CVE-1", "high"), finding("CVE-2", "medium"))}),
        artifact(
            component,
            "2.0",
            age=1,
            scans={
                "osv": scan(
                    # Same advisory under another id, on a bumped package: not new.
                    finding("GHSA-1", "high", aliases=["CVE-1"]),
                    finding("CVE-3", "critical"),
                    finding("CVE-4", "low"),
                )
            },
        ),
    ]

    newest, oldest = build_version_rows(component.id, items)

    assert newest["vulnerabilities"] == {"state": "open", "critical": 1, "high": 1, "other": 1, "new": 2}
    assert oldest["vulnerabilities"]["new"] is None


def test_the_oldest_row_shown_still_compares_against_the_version_before_it(component: Component) -> None:
    items = [
        artifact(component, f"{n}.0", age=10 - n, scans={"osv": scan(finding("CVE-1", "high"))})
        for n in range(VERSION_LIMIT + 1)
    ]

    rows = build_version_rows(component.id, items)

    assert len(rows) == VERSION_LIMIT
    assert rows[-1]["vulnerabilities"]["new"] == 0


@pytest.mark.parametrize(
    ("scans", "state"),
    [
        ({}, "not_scanned"),
        ({"osv": SKIPPED, "dependency-track": SKIPPED}, "nothing_scanned"),
        ({"osv": SKIPPED, "dependency-track": scan()}, "none"),
    ],
)
def test_scan_states_are_kept_apart(component: Component, scans: dict, state: str) -> None:
    (row,) = build_version_rows(component.id, [artifact(component, "1.0", age=1, scans=scans)])

    assert row["vulnerabilities"] == {"state": state}


def test_a_vex_suppressed_finding_is_not_open(component: Component) -> None:
    suppressed = finding("CVE-1", "critical") | {"analysis_state": "not_affected"}
    items = [artifact(component, "1.0", age=1, scans={"osv": scan(suppressed, finding("CVE-2", "high"))})]

    (row,) = build_version_rows(component.id, items)

    assert row["vulnerabilities"]["critical"] == 0
    assert row["vulnerabilities"]["high"] == 1


@pytest.mark.parametrize(
    ("plugins", "expected"),
    [
        ([], {"state": "none"}),
        ([check("OSV", "fail", category="security")], {"state": "none"}),
        ([check("NTIA", "pass"), check("CRA", "skipped")], {"state": "meets", "total": 1}),
        ([check("NTIA", "pass"), check("CRA", "pending")], {"state": "checking"}),
        (
            [check("NTIA", "fail"), check("BSI", "fail"), check("CRA", "error")],
            {"state": "fails", "first": "BSI", "more": 1},
        ),
        ([check("NTIA", "pass"), check("Attestation", "error")], {"state": "error", "first": "Attestation", "more": 0}),
    ],
)
def test_compliance_names_the_first_failing_check_and_ignores_scanners(
    component: Component, plugins: list[dict], expected: dict
) -> None:
    (row,) = build_version_rows(component.id, [artifact(component, "1.0", age=1, plugins=plugins)])

    assert row["compliance"] == expected


def test_a_check_fails_the_version_when_it_fails_any_of_its_files(component: Component) -> None:
    items = [
        artifact(component, "1.0", age=1, file_format="spdx", plugins=[check("NTIA", "pass")]),
        artifact(component, "1.0", age=1, plugins=[check("NTIA", "fail")]),
    ]

    (row,) = build_version_rows(component.id, items)

    assert row["compliance"] == {"state": "fails", "first": "NTIA", "more": 0}


def test_a_version_with_no_sbom_is_not_called_unscanned(component: Component) -> None:
    """A VEX is never scanned, so saying it was not would be a claim about nothing."""
    (row,) = build_version_rows(component.id, [artifact(component, "2026-08-19", age=1, bom_type="vex")])

    assert row["vulnerabilities"] == {"state": "not_applicable"}
    assert row["files"] == "VEX"

"""Every advisory is reachable through bounded finding-level pagination."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk import RunReason
from sbomify.apps.sboms.services.vulnerability_report import PAGE_SIZE

from ..models import SBOM
from .fixtures import sample_component, sample_sbom  # noqa: F401
from .test_views import setup_test_session

pytestmark = pytest.mark.django_db


def _run(sbom: SBOM, findings: list[dict]) -> AssessmentRun:
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="dependency-track",
        plugin_version="1.0",
        plugin_config_hash="x",
        category="security",
        status="completed",
        run_reason=RunReason.MANUAL.value,
        result={"findings": findings},
    )


def _finding(advisory: str, package: str, severity: str = "medium") -> dict:
    return {
        "id": advisory,
        "severity": severity,
        "component": {"name": package, "version": "1.0", "ecosystem": "deb"},
    }


def _client(sbom: SBOM) -> Client:
    client = Client()
    team = sbom.component.team
    setup_test_session(client, team, team.members.first())
    return client


def _report(sbom: SBOM, **params):
    return _client(sbom).get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sbom.id}), params)


def test_a_large_scan_renders_one_page(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}") for n in range(60)])
    response = _report(sample_sbom)
    assert len(response.context["scan_panel"]["rows"]) == PAGE_SIZE
    assert response.context["scan_panel"]["total"] == 60
    assert "CVE-2026-0059" not in response.content.decode()


def test_all_advisories_of_one_package_are_reachable(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", "example-kernel") for n in range(80)])
    first = _report(sample_sbom, scan_per_page="50")
    second = _report(sample_sbom, scan_per_page="50", scan_page="2")
    rows = first.context["scan_panel"]["rows"] + second.context["scan_panel"]["rows"]
    assert len(first.context["scan_panel"]["rows"]) == 50
    assert len(rows) == 80
    assert len({row["id"] for row in rows}) == 80
    assert "scan_per_page=50" in first.content.decode()


def test_legacy_page_links_still_work(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}") for n in range(60)])
    panel = _report(sample_sbom, page="2").context["scan_panel"]
    assert panel["page"] == 2
    assert [row["package"] for row in panel["rows"]] == [f"pkg-{n:04d}" for n in range(25, 50)]


def test_worst_advisories_lead_even_within_one_package(sample_sbom: SBOM):  # noqa: F811
    findings = [_finding(f"CVE-2026-{n:04d}", "example-kernel", "low") for n in range(60)]
    findings.append(_finding("CVE-2026-9999", "example-kernel", "critical"))
    _run(sample_sbom, findings)
    assert _report(sample_sbom).context["scan_panel"]["rows"][0]["id"] == "CVE-2026-9999"


@pytest.mark.parametrize(
    "params, page, count",
    [
        ({"scan_page": "99"}, 3, 10),
        ({"scan_page": "banana"}, 1, 25),
        ({"scan_per_page": "1000000"}, 1, 60),
        ({"scan_per_page": "10"}, 1, 10),
    ],
)
def test_page_and_size_are_bounded(sample_sbom: SBOM, params, page, count):  # noqa: F811
    _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", "example-kernel") for n in range(60)])
    panel = _report(sample_sbom, **params).context["scan_panel"]
    assert panel["page"] == page
    assert len(panel["rows"]) == count
    assert panel["per_page"] <= 100


def test_search_reaches_advisories_beyond_the_first_page(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", "example-kernel") for n in range(80)])
    panel = _report(sample_sbom, scan_search="CVE-2026-0079").context["scan_panel"]
    assert [row["id"] for row in panel["rows"]] == ["CVE-2026-0079"]


def test_htmx_returns_only_the_report_region(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding("CVE-2026-0001", "example-kernel")])
    response = _client(sample_sbom).get(
        reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}),
        headers={"HX-Request": "true", "HX-Target": "scan-vulnerabilities"},
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert 'id="scan-vulnerabilities"' in body
    assert 'id="sidebar"' not in body
    assert 'id="triage-modal"' not in body
    assert "open-triage" in body

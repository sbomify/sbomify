"""The full scan report holds one page of packages, not all of them.

This page is where the component panel's "View full scan report" link goes, so
capping the panel without capping this would only move the timeout: both render
a card per advisory, and a BSP-class SBOM carries thousands. The panel measured
5.1 s and 8.5 MB for 2,390 findings; this page renders strictly more per
finding.

Ordering is part of the fix rather than a separate nicety. Once the list is
paged, its order decides what page one holds, and provider order would put a
critical on page 40 because that is where the scanner happened to report it.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk import RunReason
from sbomify.apps.sboms.views.sbom_vulnerabilities import PACKAGES_PER_PAGE

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


def _packages(response) -> list[dict]:
    return response.context["vulnerabilities"]["results"][0]["packages"]


def test_a_large_scan_renders_one_page_of_packages(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}") for n in range(60)])

    response = _client(sample_sbom).get(
        reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id})
    )

    assert len(_packages(response)) == PACKAGES_PER_PAGE
    assert response.context["page_obj"].paginator.count == 60
    assert "CVE-2026-0059" not in response.content.decode()


def test_the_second_page_continues_the_list(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}") for n in range(60)])

    response = _client(sample_sbom).get(
        reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}), {"page": "2"}
    )

    names = [p["package"]["name"] for p in _packages(response)]
    assert names == [f"pkg-{n:04d}" for n in range(25, 50)]
    assert response.context["page_obj"].number == 2


def test_the_worst_package_is_on_the_first_page(sample_sbom: SBOM):  # noqa: F811
    """Provider order would have buried it, which is the trap paging introduces."""
    findings = [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}", severity="low") for n in range(60)]
    findings.append(_finding("CVE-2026-9999", "zzz-last-reported", severity="critical"))
    _run(sample_sbom, findings)

    response = _client(sample_sbom).get(
        reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id})
    )

    assert _packages(response)[0]["package"]["name"] == "zzz-last-reported"


def test_a_small_scan_still_shows_everything_with_no_pager(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding("CVE-2026-1", "openssl"), _finding("CVE-2026-2", "zlib")])

    response = _client(sample_sbom).get(
        reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id})
    )

    assert len(_packages(response)) == 2
    assert response.context["page_obj"].has_other_pages() is False
    assert "Package pagination" not in response.content.decode()


def test_a_page_past_the_end_lands_on_the_last_one(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}") for n in range(60)])

    response = _client(sample_sbom).get(
        reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}), {"page": "99"}
    )

    assert response.status_code == 200
    assert response.context["page_obj"].number == 3
    assert _packages(response)


def test_a_nonsense_page_reads_as_the_first(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}") for n in range(60)])

    response = _client(sample_sbom).get(
        reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}), {"page": "banana"}
    )

    assert response.status_code == 200
    assert response.context["page_obj"].number == 1

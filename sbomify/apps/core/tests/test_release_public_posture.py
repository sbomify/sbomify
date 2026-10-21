"""The public (Trust Center) release page never shows a vulnerability posture.

Which vulnerabilities a release is carrying is not published on the Trust
Center, to anonymous readers or to members of the workspace browsing it.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM


def _scanned_sbom(team, release, *, name: str, visibility: str, finding_id: str) -> SBOM:
    component = Component.objects.create(name=name, team=team, visibility=visibility)
    sbom = SBOM.objects.create(
        name=name, format="cyclonedx", format_version="1.6", sbom_filename=f"{name}.json", component=component
    )
    ReleaseArtifact.objects.create(release=release, sbom=sbom)
    AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        plugin_version="1.0.0",
        plugin_config_hash="",
        category="security",
        run_reason="on_upload",
        status="completed",
        result={
            "findings": [
                {"id": finding_id, "severity": "high", "component": {"name": f"{name}-pkg"}},
                {
                    "id": f"{finding_id}-suppressed",
                    "severity": "critical",
                    "component": {"name": f"{name}-other"},
                    "analysis_state": "not_affected",
                    "analysis_justification": "code_not_reachable",
                },
            ],
            "summary": {"by_severity": {"high": 1}, "total_findings": 1, "suppressed_count": 1},
        },
    )
    return sbom


def _public_release_with_scan(team):
    product = Product.objects.create(name="Public P", team=team, is_public=True)
    release = Release.objects.create(product=product, name="v1.0.0")
    _scanned_sbom(team, release, name="c", visibility=Component.Visibility.PUBLIC, finding_id="CVE-2026-1")
    return product, release


def _url(product, release) -> str:
    return reverse("core:release_details_public", kwargs={"product_id": product.id, "release_id": release.id})


def _assert_no_posture(html: str) -> None:
    assert "Vulnerability posture" not in html
    assert 'id="vuln-posture-data"' not in html
    assert "CVE-2026-1" not in html


@pytest.mark.django_db
def test_an_anonymous_reader_sees_no_vulnerability_posture(sample_team_with_owner_member):
    product, release = _public_release_with_scan(sample_team_with_owner_member.team)

    resp = Client().get(_url(product, release))

    assert resp.status_code == 200
    _assert_no_posture(resp.content.decode())


@pytest.mark.django_db
def test_a_member_managing_the_release_sees_no_vulnerability_posture(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    product, release = _public_release_with_scan(team)
    _scanned_sbom(team, release, name="secret", visibility=Component.Visibility.PRIVATE, finding_id="CVE-2026-PRIVATE")

    client = Client()
    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
    resp = client.get(_url(product, release))

    assert resp.status_code == 200
    _assert_no_posture(resp.content.decode())

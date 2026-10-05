"""What the public (Trust Center) release page says about vulnerabilities.

The posture card is published only where the workspace has asked for it, and
even then it counts public components alone. A workspace member managing the
release is not the public and keeps seeing all of it.
"""

from __future__ import annotations

import json
import re

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


def _public_release_with_scan(team, *, publish_posture: bool = True):
    if publish_posture:
        team.publish_vulnerability_posture = True
        team.save(update_fields=["publish_vulnerability_posture"])
    product = Product.objects.create(name="Public P", team=team, is_public=True)
    release = Release.objects.create(product=product, name="v1.0.0")
    _scanned_sbom(team, release, name="c", visibility=Component.Visibility.PUBLIC, finding_id="CVE-2026-1")
    return product, release


def _posture_of(html: str) -> dict:
    match = re.search(r'<script id="vuln-posture-data"[^>]*>(.*?)</script>', html, re.DOTALL)
    assert match is not None
    return json.loads(match.group(1))


def _url(product, release) -> str:
    return reverse("core:release_details_public", kwargs={"product_id": product.id, "release_id": release.id})


@pytest.mark.django_db
def test_public_release_page_shows_vuln_posture(sample_team_with_owner_member):
    product, release = _public_release_with_scan(sample_team_with_owner_member.team)

    resp = Client().get(_url(product, release))

    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Vulnerability posture" in html
    assert 'id="vuln-posture-data"' in html

    # The VEX-applied breakdown: the active high counts, the not_affected
    # critical is suppressed (dropped from counts) but still listed with its state.
    posture = _posture_of(html)
    assert posture["counts"] == {
        "critical": 0,
        "high": 1,
        "medium": 0,
        "low": 0,
        "unknown": 0,
        "total": 1,
        "malicious": 0,
    }
    assert posture["suppressed_count"] == 1
    by_id = {f["id"]: f for f in posture["findings"]}
    assert by_id["CVE-2026-1"]["suppressed"] is False
    assert by_id["CVE-2026-1-suppressed"]["suppressed"] is True
    assert by_id["CVE-2026-1-suppressed"]["state"] == "not_affected"


@pytest.mark.django_db
def test_a_workspace_that_has_not_opted_in_publishes_nothing(sample_team_with_owner_member):
    """The default. A Trust Center is readable by anyone holding the link, so
    the posture is not published until the workspace says to publish it."""
    product, release = _public_release_with_scan(sample_team_with_owner_member.team, publish_posture=False)

    resp = Client().get(_url(product, release))

    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Vulnerability posture" not in html
    assert "vuln-posture-data" not in html
    assert "CVE-2026-1" not in html


@pytest.mark.django_db
def test_a_private_component_is_never_counted_publicly(sample_team_with_owner_member):
    """The artifact table refuses to name a private component, so the posture
    must not republish its CVEs through the summary above it."""
    team = sample_team_with_owner_member.team
    product, release = _public_release_with_scan(team)
    _scanned_sbom(team, release, name="secret", visibility=Component.Visibility.PRIVATE, finding_id="CVE-2026-PRIVATE")

    html = Client().get(_url(product, release)).content.decode()

    assert "CVE-2026-PRIVATE" not in html
    posture = _posture_of(html)
    assert posture["counts"]["total"] == 1
    assert {f["id"] for f in posture["findings"]} == {"CVE-2026-1", "CVE-2026-1-suppressed"}


@pytest.mark.django_db
def test_a_gated_component_is_never_counted_publicly(sample_team_with_owner_member):
    """Gated means someone has to ask first. Naming the component is not the
    same as handing over the vulnerabilities it carries."""
    team = sample_team_with_owner_member.team
    product, release = _public_release_with_scan(team)
    _scanned_sbom(team, release, name="gated", visibility=Component.Visibility.GATED, finding_id="CVE-2026-GATED")

    html = Client().get(_url(product, release)).content.decode()

    assert "CVE-2026-GATED" not in html
    assert _posture_of(html)["counts"]["total"] == 1


@pytest.mark.django_db
def test_a_member_managing_the_release_still_sees_everything(sample_team_with_owner_member):
    """The opt-in is about the public, not about the workspace's own view."""
    team = sample_team_with_owner_member.team
    product, release = _public_release_with_scan(team, publish_posture=False)
    _scanned_sbom(team, release, name="secret", visibility=Component.Visibility.PRIVATE, finding_id="CVE-2026-PRIVATE")

    client = Client()
    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
    html = client.get(_url(product, release)).content.decode()

    posture = _posture_of(html)
    assert posture["counts"]["total"] == 2
    assert "CVE-2026-PRIVATE" in {f["id"] for f in posture["findings"]}


@pytest.mark.django_db
def test_public_release_page_no_posture_without_scans(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    team.publish_vulnerability_posture = True
    team.save(update_fields=["publish_vulnerability_posture"])
    product = Product.objects.create(name="Empty P", team=team, is_public=True)
    release = Release.objects.create(product=product, name="v1.0.0")

    resp = Client().get(_url(product, release))

    assert resp.status_code == 200
    assert "Vulnerability posture" not in resp.content.decode()

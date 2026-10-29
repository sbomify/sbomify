"""The release page shows the vulnerabilities the product page counted for it."""

from __future__ import annotations

import pytest
from django.test import Client, RequestFactory
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.services.release_lifecycle import set_release_state
from sbomify.apps.core.services.release_vulnerabilities import build_release_vulnerabilities
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member, Team
from sbomify.apps.vulnerability_scanning.posture import build_release_vuln_postures

pytestmark = pytest.mark.django_db


def _sbom(component: Component, name: str, findings: list[dict] | None) -> SBOM:
    sbom = SBOM.objects.create(name=name, component=component, version=name, format="cyclonedx")
    if findings is not None:
        AssessmentRun.objects.create(
            sbom=sbom, plugin_name="osv", category="security", status="completed", result={"findings": findings}
        )
    return sbom


def _finding(advisory: str, severity: str, package: str = "pkg") -> dict:
    return {"id": advisory, "severity": severity, "component": {"name": package, "version": "1.0"}}


@pytest.fixture
def release(sample_team_with_owner_member: Member) -> Release:
    team = sample_team_with_owner_member.team
    product = Product.objects.create(team=team, name="Example")
    component = Component.objects.create(team=team, name="Library")
    release = Release.objects.create(product=product, name="v1")
    scanned = _sbom(component, "scanned", [_finding("CVE-1", "critical"), _finding("CVE-2", "high", "other")])
    clean = _sbom(component, "clean", [])
    unscanned = _sbom(component, "unscanned", None)
    for sbom in (scanned, clean, unscanned):
        ReleaseArtifact.objects.create(release=release, sbom=sbom)
    return release


def _request(member: Member):
    request = RequestFactory().get("/")
    request.user = member.user
    request.session = {"current_team": {"key": member.team.key, "role": "owner"}}
    return request


def test_rollup_matches_the_product_page_and_counts_each_artifact(
    sample_team_with_owner_member: Member, release: Release
) -> None:
    result = build_release_vulnerabilities(_request(sample_team_with_owner_member), release.id)

    assert result.ok, result.error
    data = result.value
    rollup = build_release_vuln_postures([release])[release.id]
    assert data["counts"]["total"] == rollup["counts"]["total"] == 2
    assert (data["counts"]["critical"], data["counts"]["high"]) == (1, 1)
    assert data["unassessed"] == 1
    assert [f["id"] for f in data["findings"]] == ["CVE-1", "CVE-2"]
    assert {f["status"] for f in data["findings"]} == {"Open"}

    by_name = {a.sbom.name: a.sbom_id for a in ReleaseArtifact.objects.filter(release=release).select_related("sbom")}
    artifacts = data["artifacts"]
    assert artifacts[by_name["scanned"]]["total"] == 2
    assert artifacts[by_name["scanned"]]["url"] == reverse("sboms:sbom_vulnerabilities", args=[by_name["scanned"]])
    assert artifacts[by_name["clean"]]["total"] == 0
    assert artifacts[by_name["unscanned"]] is None


def test_outsider_is_refused(release: Release, django_user_model) -> None:
    outsider = Member.objects.create(
        team=Team.objects.create(name="Elsewhere"),
        user=django_user_model.objects.create_user(username="outsider", email="outsider@example.com"),
        role="owner",
    )

    result = build_release_vulnerabilities(_request(outsider), release.id)

    assert not result.ok
    assert result.status_code == 403


def test_release_page_lists_vulnerabilities(
    client: Client, sample_team_with_owner_member: Member, release: Release, mocker: MockerFixture
) -> None:
    member = sample_team_with_owner_member
    setup_authenticated_client_session(client, member.team, member.user)
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)

    response = client.get(reverse("core:release_details", args=[release.product_id, release.id]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "<c-" not in content
    assert 'id="release-vulnerabilities"' in content
    assert "CVE-1" in content and "CVE-2" in content
    assert "1 SBOM not scanned yet" in content
    assert 'id="release-artifact-vulnerabilities"' in content


def test_a_retired_release_page_says_its_unscanned_sboms_were_never_scanned(
    client: Client, sample_team_with_owner_member: Member, release: Release, mocker: MockerFixture
) -> None:
    member = sample_team_with_owner_member
    setup_authenticated_client_session(client, member.team, member.user)
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)
    component = ReleaseArtifact.objects.filter(release=release).first().sbom.component
    _sbom(component, "next", [])  # newer, so nothing the release ships is scanned any more
    assert set_release_state(release, "withdraw", reason="defective").ok

    response = client.get(reverse("core:release_details", args=[release.product_id, release.id]))

    content = response.content.decode()
    assert "1 SBOM never scanned" in content
    assert "not scanned yet" not in content


def test_release_without_sboms_has_no_vulnerabilities_section(
    client: Client, sample_team_with_owner_member: Member, mocker: MockerFixture
) -> None:
    member = sample_team_with_owner_member
    release = Release.objects.create(product=Product.objects.create(team=member.team, name="Empty"), name="v1")
    setup_authenticated_client_session(client, member.team, member.user)
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)

    response = client.get(reverse("core:release_details", args=[release.product_id, release.id]))

    assert response.status_code == 200
    assert 'id="release-vulnerabilities"' not in response.content.decode()

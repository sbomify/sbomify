"""What changed between two releases: components added/removed/bumped,
vulnerabilities introduced/resolved."""

from __future__ import annotations

import json

import pytest

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.services import csv_exports, release_diff
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM


def _doc(packages: list[tuple[str, str]]) -> dict:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": [
            {"type": "library", "name": name, "version": version, "licenses": [{"expression": "MIT"}]}
            for name, version in packages
        ],
    }


def _scan(sbom: SBOM, vulns: list[tuple[str, str]]) -> AssessmentRun:
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        plugin_version="1",
        plugin_config_hash="",
        category="security",
        run_reason="on_upload",
        status="completed",
        result={
            "findings": [
                {"id": vuln_id, "severity": severity, "component": {"name": "requests", "version": "1"}}
                for vuln_id, severity in vulns
            ]
        },
    )


@pytest.fixture
def two_releases(sample_team_with_owner_member, monkeypatch):
    team = sample_team_with_owner_member.team
    product = Product.objects.create(name="Prod", team=team)
    component = Component.objects.create(name="app", team=team)
    component.products.add(product)

    docs: dict[str, dict] = {}

    def make(version: str, packages: list[tuple[str, str]], vulns: list[tuple[str, str]]) -> Release:
        sbom = SBOM.objects.create(
            name="app",
            version=version,
            format="cyclonedx",
            format_version="1.6",
            sbom_filename=f"{version}.json",
            component=component,
        )
        docs[sbom.id] = _doc(packages)
        _scan(sbom, vulns)
        release = Release.objects.create(product=product, name=f"v{version}")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)
        return release

    old = make("1.4", [("requests", "2.31.0"), ("dropped-lib", "1.0")], [("CVE-OLD", "high")])
    new = make("1.5", [("requests", "2.32.3"), ("added-lib", "3.1")], [("CVE-NEW", "critical")])

    def fake(sbom_id):
        return SBOM.objects.get(id=sbom_id), json.dumps(docs[sbom_id]).encode()

    monkeypatch.setattr(csv_exports, "get_sbom_data_bytes", fake)
    return team, product, old, new


@pytest.mark.django_db
class TestDiffService:
    def test_component_add_remove_bump(self, two_releases):
        team, _, old, new = two_releases
        result = release_diff.diff_releases(team, old, new)
        assert result.ok
        diff = result.value
        assert [c["name"] for c in diff["components"]["added"]] == ["added-lib"]
        assert [c["name"] for c in diff["components"]["removed"]] == ["dropped-lib"]
        changed = diff["components"]["changed"]
        assert changed == [{"name": "requests", "from_version": "2.31.0", "to_version": "2.32.3"}]

    def test_vulnerability_introduced_and_resolved(self, two_releases):
        team, _, old, new = two_releases
        diff = release_diff.diff_releases(team, old, new).value
        assert [v["id"] for v in diff["vulnerabilities"]["introduced"]] == ["CVE-NEW"]
        assert [v["id"] for v in diff["vulnerabilities"]["resolved"]] == ["CVE-OLD"]

    def test_releases_of_different_products_are_refused(self, two_releases):
        team, _, old, _ = two_releases
        other_product = Product.objects.create(name="Other", team=team)
        foreign = Release.objects.create(product=other_product, name="vX")
        result = release_diff.diff_releases(team, old, foreign)
        assert not result.ok


@pytest.mark.django_db
class TestDiffEndpoint:
    def test_json_endpoint(self, authenticated_api_client, two_releases):
        client, token = authenticated_api_client
        from sbomify.apps.core.tests.shared_fixtures import get_api_headers

        _, _, old, new = two_releases
        response = client.get(
            f"/api/v1/release-diff?from_release_id={old.id}&to_release_id={new.id}",
            **get_api_headers(token),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["components"]["added"][0]["name"] == "added-lib"

    def test_foreign_release_is_not_found(self, authenticated_api_client, two_releases, guest_user):
        client, token = authenticated_api_client
        from sbomify.apps.core.tests.shared_fixtures import get_api_headers
        from sbomify.apps.teams.models import Member, Team

        _, _, old, _ = two_releases
        foreign_team = Team.objects.create(name="Foreign")
        Member.objects.create(user=guest_user, team=foreign_team, role="owner")
        foreign_product = Product.objects.create(name="FP", team=foreign_team)
        foreign_release = Release.objects.create(product=foreign_product, name="vF")

        response = client.get(
            f"/api/v1/release-diff?from_release_id={old.id}&to_release_id={foreign_release.id}",
            **get_api_headers(token),
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestDiffPage:
    def test_page_renders_sections(self, authenticated_web_client, two_releases, sample_user):
        team, product, old, new = two_releases
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        setup_authenticated_client_session(authenticated_web_client, team, sample_user)
        response = authenticated_web_client.get(f"/product/{product.id}/release/{new.id}/diff/{old.id}/")
        assert response.status_code == 200
        body = response.content.decode()
        assert "added-lib" in body
        assert "dropped-lib" in body
        assert "CVE-NEW" in body
        assert "CVE-OLD" in body

    def test_release_page_links_to_compare(self, authenticated_web_client, two_releases, sample_user):
        team, product, old, new = two_releases
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        setup_authenticated_client_session(authenticated_web_client, team, sample_user)
        response = authenticated_web_client.get(f"/product/{product.id}/release/{new.id}/")
        assert response.status_code == 200
        assert f"/diff/{old.id}/" in response.content.decode()


@pytest.mark.django_db
class TestUnreadableArtifacts:
    def test_unreadable_pinned_sbom_is_reported_not_skipped(self, two_releases, monkeypatch):
        team, _, old, new = two_releases

        def broken(sbom_id):
            raise csv_exports.SBOMDataError("gone")

        monkeypatch.setattr(csv_exports, "get_sbom_data_bytes", broken)
        diff = release_diff.diff_releases(team, old, new).value
        assert len(diff["unreadable_artifacts"]) == 2

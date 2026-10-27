"""A release sbomify no longer monitors says when it was last scanned, and never reads as clean."""

from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as dt_timezone
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.services.release_lifecycle import untracked_notice
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Workspace
from sbomify.apps.vulnerability_scanning.posture import build_release_vuln_posture, build_release_vuln_postures

pytestmark = pytest.mark.django_db

OLDEST = datetime(2025, 3, 2, 12, tzinfo=dt_timezone.utc)
NEWER = datetime(2025, 3, 9, 12, tzinfo=dt_timezone.utc)
WITHDRAWN = datetime(2025, 3, 3, 12, tzinfo=dt_timezone.utc)


def _scan(release: Release, name: str, completed_at: datetime, findings: list[dict[str, Any]]) -> SBOM:
    component = Component.objects.create(
        team=release.product.team, name=name, visibility=Component.Visibility.PUBLIC
    )
    sbom = SBOM.objects.create(name=name, component=component, version="1.0", format="cyclonedx")
    ReleaseArtifact.objects.create(release=release, sbom=sbom)
    AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        category="security",
        status="completed",
        completed_at=completed_at,
        result={"findings": findings},
    )
    return sbom


def _finding(advisory: str) -> dict[str, Any]:
    return {"id": advisory, "severity": "high", "component": {"name": "pkg", "version": "1.0"}}


def _withdraw(release: Release) -> None:
    Release.objects.filter(pk=release.pk).update(withdrawn_at=WITHDRAWN, withdrawn_reason="defective")


def _product(team: Workspace, name: str = "Gateway", **fields: Any) -> Product:
    return Product.objects.create(team=team, name=name, **fields)


class TestLastScanned:
    def test_is_the_stalest_of_the_latest_scans(self, team_with_business_plan: Workspace) -> None:
        release = Release.objects.create(product=_product(team_with_business_plan, is_public=True), name="1.0.0")
        # The SBOM's first run is not its latest, so it does not date the release.
        stale = _scan(release, "stale", datetime(2024, 1, 1, tzinfo=dt_timezone.utc), [])
        AssessmentRun.objects.create(
            sbom=stale,
            plugin_name="osv",
            category="security",
            status="completed",
            completed_at=OLDEST,
            result={"findings": [_finding("CVE-1")]},
        )
        _scan(release, "fresh", NEWER, [])

        assert build_release_vuln_postures([release])[release.id]["last_scanned_at"] == OLDEST
        assert build_release_vuln_posture(release)["last_scanned_at"] == OLDEST


class TestUntrackedNotice:
    def _release(self, team: Workspace, **fields: Any) -> Release:
        product = _product(team, **fields.pop("product_fields", {}))
        release = Release.objects.create(product=product, name="1.0.0")
        Release.objects.filter(pk=release.pk).update(**fields)
        return Release.objects.select_related("product").get(pk=release.pk)

    @pytest.mark.parametrize(
        ("fields", "since", "reason"),
        [
            ({"withdrawn_at": WITHDRAWN}, WITHDRAWN, "It was withdrawn."),
            ({"end_of_life": date(2025, 3, 2)}, date(2025, 3, 3), "It reached end of life."),
            ({"end_of_support": date(2025, 3, 2)}, date(2025, 3, 3), "Its support ended."),
            (
                {"product_fields": {"end_of_support": date(2025, 3, 2)}},
                date(2025, 3, 3),
                "Its support ended.",
            ),
            ({"superseded_at": WITHDRAWN}, WITHDRAWN, "A newer release replaced it."),
            ({"archived_at": WITHDRAWN}, WITHDRAWN, "It was archived."),
        ],
    )
    def test_says_since_when_and_why(
        self, team_with_business_plan: Workspace, fields: dict[str, Any], since: date, reason: str
    ) -> None:
        assert untracked_notice(self._release(team_with_business_plan, **fields)) == {"since": since, "reason": reason}

    def test_a_monitored_release_has_none(self, team_with_business_plan: Workspace) -> None:
        assert untracked_notice(self._release(team_with_business_plan)) is None
        latest = self._release(
            team_with_business_plan, is_latest=True, end_of_life=date(2025, 3, 2), product_fields={"name": "Console"}
        )
        assert untracked_notice(latest) is None


class TestReleasePage:
    def _page(self, client: Client, release: Release) -> str:
        response = client.get(reverse("core:release_details", args=[release.product_id, release.id]))
        assert response.status_code == 200
        return " ".join(response.content.decode().split())

    def test_a_retired_release_dates_its_counts(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        release = Release.objects.create(product=_product(team_with_business_plan), name="1.0.0")
        _scan(release, "lib", OLDEST, [_finding("CVE-1")])
        _withdraw(release)

        page = self._page(authenticated_web_client, release)
        assert "Not monitored since 3 Mar 2025" in page
        assert "It was withdrawn. These counts are from its last scan, on 2 Mar 2025." in page

    def test_a_retired_release_with_no_findings_is_not_called_clean(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        release = Release.objects.create(product=_product(team_with_business_plan), name="1.0.0")
        _scan(release, "lib", OLDEST, [])
        _withdraw(release)

        page = self._page(authenticated_web_client, release)
        assert "No vulnerabilities at last scan" in page
        assert "No vulnerabilities found" not in page

    def test_a_monitored_release_is_unchanged(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        release = Release.objects.create(product=_product(team_with_business_plan), name="1.0.0")
        _scan(release, "lib", OLDEST, [])

        page = self._page(authenticated_web_client, release)
        assert "No vulnerabilities found" in page
        assert "Not monitored since" not in page
        assert "at last scan" not in page


class TestTrustCenter:
    def _page(self, release: Release) -> str:
        url = reverse("core:release_details_public", args=[release.product_id, release.id])
        response = Client().get(url)
        assert response.status_code == 200
        return " ".join(response.content.decode().split())

    def _release(self) -> Release:
        workspace = Workspace.objects.create(name="Public", is_public=True, publish_vulnerability_posture=True)
        return Release.objects.create(product=_product(workspace, is_public=True), name="1.0.0")

    def test_a_retired_release_dates_its_posture(self) -> None:
        release = self._release()
        _scan(release, "lib", OLDEST, [_finding("CVE-1")])
        _withdraw(release)

        page = self._page(release)
        assert "Not monitored since 3 Mar 2025" in page
        assert "These counts are from its last scan, on 2 Mar 2025." in page

    def test_a_retired_release_with_no_findings_is_not_called_clean(self) -> None:
        release = self._release()
        _scan(release, "lib", OLDEST, [])
        _withdraw(release)

        page = self._page(release)
        assert "No known vulnerabilities at its last scan." in page
        assert "No vulnerabilities found in this release." not in page

    def test_a_monitored_release_is_unchanged(self) -> None:
        release = self._release()
        _scan(release, "lib", OLDEST, [])

        page = self._page(release)
        assert "No vulnerabilities found in this release." in page
        assert "Not monitored since" not in page


class TestReleasesList:
    def test_a_retired_release_says_when_it_was_last_scanned(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = _product(team_with_business_plan)
        retired = Release.objects.create(product=product, name="1.0.0")
        _scan(retired, "old", OLDEST, [])
        _withdraw(retired)
        monitored = Release.objects.create(product=product, name="1.1.0")
        _scan(monitored, "new", NEWER, [])

        page = " ".join(
            authenticated_web_client.get(reverse("core:product_releases", args=[product.id])).content.decode().split()
        )
        assert page.count("None at last scan") == 1
        assert page.count("Last scanned 2 Mar 2025") == 1
        assert "Last scanned 9 Mar 2025" not in page

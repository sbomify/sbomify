"""A release sbomify no longer monitors says when it was last scanned, and never reads as clean."""

from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as dt_timezone
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact, ReleaseLink
from sbomify.apps.core.services.cle import create_cle_event
from sbomify.apps.core.services.release_lifecycle import recompute_release_lifecycle, untracked_notice
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Workspace
from sbomify.apps.vulnerability_scanning.posture import build_release_vuln_posture, build_release_vuln_postures

pytestmark = pytest.mark.django_db

OLDEST = datetime(2025, 3, 2, 12, tzinfo=dt_timezone.utc)
NEWER = datetime(2025, 3, 9, 12, tzinfo=dt_timezone.utc)
WITHDRAWN = datetime(2025, 3, 3, 12, tzinfo=dt_timezone.utc)


def _scan(release: Release, name: str, completed_at: datetime, findings: list[dict[str, Any]]) -> SBOM:
    component = Component.objects.create(team=release.product.team, name=name, visibility=Component.Visibility.PUBLIC)
    sbom = SBOM.objects.create(name=name, component=component, version="1.0", format="cyclonedx")
    # A newer upload, so the release's SBOM is history: a component's newest SBOM is always scanned.
    SBOM.objects.create(name=name, component=component, version="2.0", format="cyclonedx")
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
        if product_support := fields.pop("product_end_of_support", None):
            # A product date for every version, as the lifecycle card records it.
            effective = datetime.combine(product_support, datetime.min.time(), tzinfo=dt_timezone.utc)
            assert create_cle_event(product, "endOfSupport", effective, versions=[{"range": "vers:generic/*"}]).ok
        release = Release.objects.create(product=product, name="1.0.0")
        recompute_release_lifecycle(product)
        for own in ("end_of_support", "end_of_life"):
            if own in fields:
                fields[f"effective_{own}"] = fields[own]
        Release.objects.filter(pk=release.pk).update(**fields)
        return Release.objects.select_related("product").get(pk=release.pk)

    @pytest.mark.parametrize(
        ("fields", "on", "reason"),
        [
            ({"withdrawn_at": WITHDRAWN}, WITHDRAWN.date(), "It was withdrawn"),
            ({"end_of_life": date(2025, 3, 2)}, date(2025, 3, 2), "It reached end of life"),
            ({"end_of_support": date(2025, 3, 2)}, date(2025, 3, 2), "Its support ended"),
            ({"product_end_of_support": date(2025, 3, 2)}, date(2025, 3, 2), "Its support ended"),
            ({"superseded_at": WITHDRAWN}, WITHDRAWN.date(), "A newer release replaced it"),
            ({"archived_at": WITHDRAWN}, WITHDRAWN.date(), "It was archived"),
        ],
    )
    def test_says_why_and_on_what_date(
        self, team_with_business_plan: Workspace, fields: dict[str, Any], on: date, reason: str
    ) -> None:
        assert untracked_notice(self._release(team_with_business_plan, **fields)) == {"on": on, "reason": reason}

    def test_a_monitored_release_has_none(self, team_with_business_plan: Workspace) -> None:
        assert untracked_notice(self._release(team_with_business_plan)) is None
        latest = self._release(
            team_with_business_plan, is_latest=True, end_of_life=date(2025, 3, 2), product_fields={"name": "Console"}
        )
        assert untracked_notice(latest) is None

    def test_a_retired_release_a_live_release_links_to_is_still_monitored(
        self, team_with_business_plan: Workspace
    ) -> None:
        linked = self._release(team_with_business_plan, withdrawn_at=WITHDRAWN)
        linking = Release.objects.create(product=_product(team_with_business_plan, name="Console"), name="2.0.0")
        ReleaseLink.objects.create(release=linking, linked_release=linked)
        assert untracked_notice(linked) is None

    def test_names_the_first_thing_that_stopped_the_scans(self, team_with_business_plan: Workspace) -> None:
        # Replaced in June 2025; the product's support ended later, in January 2026.
        release = self._release(
            team_with_business_plan,
            superseded_at=datetime(2025, 6, 1, tzinfo=dt_timezone.utc),
            product_end_of_support=date(2026, 1, 1),
        )
        assert untracked_notice(release) == {"on": date(2025, 6, 1), "reason": "A newer release replaced it"}

    def test_a_retired_release_whose_sboms_a_live_release_ships_is_still_monitored(
        self, team_with_business_plan: Workspace
    ) -> None:
        product = _product(team_with_business_plan)
        retired = Release.objects.create(product=product, name="1.0.0")
        shared = _scan(retired, "lib", OLDEST, [])
        _withdraw(retired)
        live = Release.objects.create(product=product, name="1.1.0")
        ReleaseArtifact.objects.create(release=live, sbom=shared)
        retired = Release.objects.select_related("product").get(pk=retired.pk)
        assert untracked_notice(retired) is None

        # One SBOM it alone ships is enough for its counts to go stale.
        _scan(retired, "tool", OLDEST, [])
        assert untracked_notice(retired) == {"on": WITHDRAWN.date(), "reason": "It was withdrawn"}

    def test_a_retired_release_shipping_its_components_newest_sbom_is_still_monitored(
        self, team_with_business_plan: Workspace
    ) -> None:
        # The scheduled scans cover each component's newest SBOM, so its counts keep moving.
        retired = Release.objects.create(product=_product(team_with_business_plan), name="1.0.0")
        component = Component.objects.create(team=retired.product.team, name="lib")
        ReleaseArtifact.objects.create(
            release=retired,
            sbom=SBOM.objects.create(name="lib", component=component, version="1.0", format="cyclonedx"),
        )
        _withdraw(retired)
        retired = Release.objects.select_related("product").get(pk=retired.pk)
        assert untracked_notice(retired) is None

    def test_on_the_trust_center_only_the_sboms_it_shows_count(self, team_with_business_plan: Workspace) -> None:
        product = _product(team_with_business_plan)
        retired = Release.objects.create(product=product, name="1.0.0")
        shared = _scan(retired, "lib", OLDEST, [])
        # A private SBOM only this release ships: its counts are frozen, but the public never sees them.
        private = _scan(retired, "secret", OLDEST, [])
        Component.objects.filter(pk=private.component_id).update(visibility=Component.Visibility.PRIVATE)
        live = Release.objects.create(product=product, name="1.1.0")
        ReleaseArtifact.objects.create(release=live, sbom=shared)
        _withdraw(retired)
        retired = Release.objects.select_related("product").get(pk=retired.pk)

        assert untracked_notice(retired) == {"on": WITHDRAWN.date(), "reason": "It was withdrawn"}
        assert untracked_notice(retired, public_only=True) is None


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
        assert "No longer monitored" in page
        assert "It was withdrawn on 3 Mar 2025. These counts are from its last scan, on 2 Mar 2025." in page
        assert "Not monitored since" not in page

    def test_a_retired_release_with_no_findings_is_not_called_clean(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        release = Release.objects.create(product=_product(team_with_business_plan), name="1.0.0")
        _scan(release, "lib", OLDEST, [])
        _withdraw(release)

        page = self._page(authenticated_web_client, release)
        assert "No vulnerabilities at last scan" in page
        assert "No vulnerabilities found" not in page

    def test_a_retired_release_never_scanned_does_not_promise_results(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        release = Release.objects.create(product=_product(team_with_business_plan), name="1.0.0")
        component = Component.objects.create(team=release.product.team, name="lib")
        sbom = SBOM.objects.create(name="lib", component=component, version="1.0", format="cyclonedx")
        SBOM.objects.create(name="lib", component=component, version="2.0", format="cyclonedx")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)
        _withdraw(release)

        page = self._page(authenticated_web_client, release)
        assert "Scan results appear here once" not in page
        assert "sbomify stopped monitoring this release before its SBOMs were scanned" in page

    def test_a_monitored_release_is_unchanged(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        release = Release.objects.create(product=_product(team_with_business_plan), name="1.0.0")
        _scan(release, "lib", OLDEST, [])

        page = self._page(authenticated_web_client, release)
        assert "No vulnerabilities found" in page
        assert "No longer monitored" not in page
        assert "at last scan" not in page


class TestDatedReasons:
    def test_a_date_long_past_at_deploy_does_not_contradict_the_last_scan(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        # Support ended long ago, but the release was scanned until the deploy that retired it.
        product = _product(team_with_business_plan)
        ended = datetime(2025, 12, 31, tzinfo=dt_timezone.utc)
        assert create_cle_event(product, "endOfSupport", ended, versions=[{"range": "vers:generic/*"}]).ok
        release = Release.objects.create(product=product, name="1.0.0")
        recompute_release_lifecycle(product)
        _scan(release, "lib", datetime(2026, 10, 27, tzinfo=dt_timezone.utc), [_finding("CVE-1")])

        response = authenticated_web_client.get(reverse("core:release_details", args=[product.id, release.id]))
        page = " ".join(response.content.decode().split())

        assert "Its support ended on 31 Dec 2025. These counts are from its last scan, on 27 Oct 2026." in page
        assert "since 1 Jan 2026" not in page


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
        assert "No longer monitored" in page
        assert "It was withdrawn on 3 Mar 2025. These counts are from its last scan, on 2 Mar 2025." in page

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
        assert "No longer monitored" not in page


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

    def test_a_retired_release_never_scanned_does_not_promise_a_scan(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = _product(team_with_business_plan)
        retired = Release.objects.create(product=product, name="1.0.0")
        component = Component.objects.create(team=team_with_business_plan, name="lib")
        sbom = SBOM.objects.create(name="lib", component=component, version="1.0", format="cyclonedx")
        SBOM.objects.create(name="lib", component=component, version="2.0", format="cyclonedx")
        ReleaseArtifact.objects.create(release=retired, sbom=sbom)
        _withdraw(retired)

        page = " ".join(
            authenticated_web_client.get(reverse("core:product_releases", args=[product.id])).content.decode().split()
        )
        assert "1 SBOM never scanned" in page
        assert "not scanned yet" not in page

    def test_a_retired_release_a_live_release_links_to_is_not_frozen(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = _product(team_with_business_plan)
        linked = Release.objects.create(product=product, name="1.0.0")
        _scan(linked, "old", OLDEST, [])
        _withdraw(linked)
        linking = Release.objects.create(product=_product(team_with_business_plan, name="Console"), name="2.0.0")
        ReleaseLink.objects.create(release=linking, linked_release=linked)

        page = " ".join(
            authenticated_web_client.get(reverse("core:product_releases", args=[product.id])).content.decode().split()
        )
        assert "Last scanned" not in page
        assert "at last scan" not in page

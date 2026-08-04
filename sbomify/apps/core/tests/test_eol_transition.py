"""End-of-life transition (CRA checklist 6.1): readiness, announcement, finals."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from sbomify.apps.core.models import Product, Release, ReleaseArtifact
from sbomify.apps.core.services.eol import (
    build_eol_advisory,
    eol_readiness,
    final_artifacts,
    products_approaching_eol,
)
from sbomify.apps.plugins.models import VulnerabilityLifecycle
from sbomify.apps.sboms.models import SBOM, Component

pytestmark = pytest.mark.django_db


@pytest.fixture
def eol_product(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    product = Product.objects.create(
        team=team,
        name="Retiring Gateway",
        end_of_support=date.today() + timedelta(days=30),
        end_of_life=date.today() + timedelta(days=120),
    )
    component = Component.objects.create(team=team, name="Gateway Firmware")
    product.components.set([component])
    return product, component


def _release_with(product, component, *, bom_types=("sbom",)):
    release = Release.objects.create(product=product, name="v9.0.0", version="9.0.0")
    for index, bom_type in enumerate(bom_types):
        sbom = SBOM.objects.create(
            name=f"gateway-{bom_type}",
            version="9.0.0",
            component=component,
            format="cyclonedx",
            format_version="1.6",
            sbom_filename=f"gateway-{index}.json",
            bom_type=bom_type,
        )
        ReleaseArtifact.objects.create(release=release, sbom=sbom)
    return release


def _open_finding(component, advisory_id, severity):
    from django.utils import timezone

    now = timezone.now()
    return VulnerabilityLifecycle.objects.create(
        component=component,
        advisory_id=advisory_id,
        severity=severity,
        first_seen_at=now - timedelta(days=10),
        last_seen_at=now,
    )


class TestReadiness:
    def test_a_clean_product_with_a_final_sbom_is_ready(self, eol_product):
        product, component = eol_product
        _release_with(product, component)

        readiness = eol_readiness(product)

        assert readiness.is_ready is True
        assert readiness.problems == []
        assert readiness.has_final_sbom is True

    def test_open_criticals_and_highs_block(self, eol_product):
        product, component = eol_product
        _release_with(product, component)
        _open_finding(component, "CVE-2026-100", "critical")
        _open_finding(component, "CVE-2026-101", "high")

        readiness = eol_readiness(product)

        assert readiness.is_ready is False
        assert readiness.blocking_count == 2
        assert "critical" in readiness.problems[0]
        assert "high" in readiness.problems[1]

    def test_a_missing_final_sbom_blocks(self, eol_product):
        product, _ = eol_product

        readiness = eol_readiness(product)

        assert readiness.has_final_sbom is False
        assert "No SBOM" in readiness.problems[0]

    def test_medium_and_low_findings_do_not_block(self, eol_product):
        """6.1.6 names critical and high only."""
        product, component = eol_product
        _release_with(product, component)
        _open_finding(component, "CVE-2026-102", "medium")

        assert eol_readiness(product).is_ready is True

    def test_a_resolved_finding_does_not_block(self, eol_product):
        from django.utils import timezone

        product, component = eol_product
        _release_with(product, component)
        row = _open_finding(component, "CVE-2026-103", "critical")
        row.resolved_at = timezone.now()
        row.save()

        assert eol_readiness(product).is_ready is True

    def test_the_notice_period_is_reported(self, eol_product):
        product, component = eol_product
        _release_with(product, component)

        readiness = eol_readiness(product)

        assert readiness.days_to_end_of_life == 120
        assert readiness.days_to_end_of_support == 30
        # 120 days is short of the recommended twelve months.
        assert readiness.notice_given is False

    def test_a_vex_on_the_release_is_reported(self, eol_product):
        product, component = eol_product
        _release_with(product, component, bom_types=("sbom", "vex"))

        readiness = eol_readiness(product)

        assert readiness.has_final_sbom is True
        assert readiness.has_final_vex is True


class TestAnnouncement:
    def test_the_advisory_is_drafted_not_published(self, eol_product, sample_user):
        """An EOL notice is an irreversible public statement, so a human
        publishes it."""
        from sbomify.apps.security_advisories.models import SecurityAdvisory

        product, _ = eol_product

        advisory = build_eol_advisory(product, sample_user)

        assert advisory.status == SecurityAdvisory.Status.DRAFT
        assert advisory.remediation_status == SecurityAdvisory.RemediationStatus.WONT_FIX
        assert product.name in advisory.title

    def test_the_announcement_names_both_dates_when_they_differ(self, eol_product, sample_user):
        product, _ = eol_product

        advisory = build_eol_advisory(product, sample_user)

        assert product.end_of_life.isoformat() in advisory.description
        assert "Bug fixes stopped" in advisory.description

    def test_the_product_is_attached_and_an_event_recorded(self, eol_product, sample_user):
        product, _ = eol_product

        advisory = build_eol_advisory(product, sample_user, migration_path="Migrate to Gateway 10")

        assert advisory.products.get().product == product
        assert advisory.events.get().payload["kind"] == "eol"
        assert "Gateway 10" in advisory.description


class TestFinalArtifacts:
    def test_the_latest_release_artifacts_are_returned(self, eol_product):
        product, component = eol_product
        release = _release_with(product, component, bom_types=("sbom", "vex"))

        finals = final_artifacts(product)

        assert finals["release"] == release
        assert len(finals["sboms"]) == 1
        assert len(finals["vex"]) == 1

    def test_a_product_that_shipped_nothing_has_no_final_artifacts(self, eol_product):
        """Every product carries an auto-created floating `latest`, so the
        honest answer is a release with nothing in it — not a crash, and not
        a pretend artifact set."""
        product, _ = eol_product

        finals = final_artifacts(product)

        assert finals["sboms"] == []
        assert finals["vex"] == []
        assert eol_readiness(product).has_final_sbom is False

    def test_a_versioned_release_wins_over_the_floating_latest(self, eol_product):
        """`latest` re-targets as artifacts arrive, so pinning "final" to it
        would let the final SBOM change after support ended."""
        product, component = eol_product
        versioned = _release_with(product, component)

        assert final_artifacts(product)["release"] == versioned
        assert versioned.is_latest is False


class TestApproachingSweep:
    def test_products_inside_the_window_surface(self, eol_product, sample_team_with_owner_member):
        product, _ = eol_product

        found = products_approaching_eol(sample_team_with_owner_member.team, within_days=60)

        assert product in found  # end_of_support is 30 days out

    def test_a_product_past_its_eol_still_surfaces(self, sample_team_with_owner_member):
        """The case most worth surfacing: a product that quietly passed EOL
        without an announcement."""
        team = sample_team_with_owner_member.team
        lapsed = Product.objects.create(
            team=team, name="Long Gone", end_of_life=date.today() - timedelta(days=400)
        )

        assert lapsed in products_approaching_eol(team, within_days=30)

    def test_products_with_no_dates_are_ignored(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        Product.objects.create(team=team, name="No Dates")

        assert products_approaching_eol(team, within_days=3650) == []


class TestReadinessEndpoint:
    def test_the_endpoint_reports_the_verdict_and_the_blockers(self, eol_product, sample_team_with_owner_member):
        from django.test import Client

        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        product, component = eol_product
        _release_with(product, component)
        _open_finding(component, "CVE-2026-200", "critical")
        member = sample_team_with_owner_member
        client = Client()
        setup_authenticated_client_session(client, member.team, member.user)

        response = client.get(f"/api/v1/products/{product.id}/eol-readiness")

        assert response.status_code == 200
        body = response.json()
        assert body["is_ready"] is False
        assert body["blocking_count"] == 1
        assert body["unresolved_critical"][0]["advisory_id"] == "CVE-2026-200"
        assert body["end_of_life"] == product.end_of_life.isoformat()
        assert "critical" in body["problems"][0]

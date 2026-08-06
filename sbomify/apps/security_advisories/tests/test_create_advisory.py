"""The New Advisory write path: the modal's submission mapped onto the model.

The interesting property is the shape of the initial graph: one vulnerability
from birth, an in_triage status per product, and affected releases stored as
pinned single-version ranges — exactly what validate_publishable will demand
later, so nothing created here needs restructuring before publish.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from sbomify.apps.core.models import Product, Release
from sbomify.apps.security_advisories.forms import AdvisoryCreateForm
from sbomify.apps.security_advisories.models import (
    AdvisoryProductStatus,
    AdvisoryReference,
    SecurityAdvisory,
)
from sbomify.apps.security_advisories.services.advisories import create_advisory, creation_options

pytestmark = pytest.mark.django_db


@pytest.fixture
def release(product):
    return Release.objects.create(product=product, name="v1.2.0", version="1.2.0")


@pytest.fixture
def user(sample_team_with_owner_member):
    return sample_team_with_owner_member.user


class TestCreateAdvisory:
    def test_full_graph_with_cve_product_and_release(self, team, user, product, release):
        result = create_advisory(
            team,
            user,
            title="Improper authentication in SAML assertion handling",
            severity="high",
            description="Signature validation can be bypassed.",
            identifier="CVE-2026-12345",
            products=[product],
            affected_releases=[release],
        )

        assert result.ok
        advisory = SecurityAdvisory.objects.get(pk=result.value)
        assert advisory.team == team
        assert advisory.created_by == user
        assert advisory.severity == "high"

        vulnerability = advisory.vulnerabilities.get()
        assert vulnerability.cve_id == "CVE-2026-12345"

        advisory_product = advisory.products.get()
        assert advisory_product.product == product
        assert advisory_product.product_name == product.name

        status = vulnerability.product_statuses.get()
        assert status.advisory_product == advisory_product
        assert status.status == AdvisoryProductStatus.Status.IN_TRIAGE

        version_range = status.version_ranges.get()
        assert version_range.introduced == "1.2.0"
        assert version_range.last_affected == "1.2.0"
        assert version_range.introduced_release == release
        assert version_range.last_affected_release == release

        event = advisory.events.get()
        assert event.event_type == "status_change"
        assert event.payload == {"to": "identified"}
        assert event.actor == user

    def test_lowercase_cve_is_normalised_without_the_form(self, team, user):
        result = create_advisory(team, user, title="Direct call", identifier="cve-2026-0001")

        vulnerability = SecurityAdvisory.objects.get(pk=result.value).vulnerabilities.get()
        assert vulnerability.cve_id == "CVE-2026-0001"

    def test_non_cve_identifier_becomes_a_reference(self, team, user):
        result = create_advisory(team, user, title="Prototype pollution", identifier="GHSA-abcd-1234-wxyz")

        advisory = SecurityAdvisory.objects.get(pk=result.value)
        # A GHSA cannot live in cve_id, which validates strictly, so the
        # vulnerability keeps the advisory title as its working name.
        vulnerability = advisory.vulnerabilities.get()
        assert vulnerability.cve_id == ""
        assert vulnerability.title == "Prototype pollution"

        reference = advisory.references.get()
        assert reference.external_id == "GHSA-abcd-1234-wxyz"
        assert reference.reference_type == "ghsa"

    def test_url_identifier_lands_in_the_url_field(self, team, user):
        result = create_advisory(team, user, title="Vendor bulletin", identifier="https://example.com/vsa-1")

        reference = AdvisoryReference.objects.get(advisory_id=result.value)
        assert reference.url == "https://example.com/vsa-1"
        assert reference.external_id == ""

    def test_release_of_unselected_product_rolls_everything_back(self, team, user, product, release):
        result = create_advisory(team, user, title="Bad mapping", products=[], affected_releases=[release])

        assert not result.ok
        assert SecurityAdvisory.objects.count() == 0

    def test_latest_release_rejected_without_the_form(self, team, user, product):
        floating = Release.objects.create(product=product, name="latest", is_latest=True)
        result = create_advisory(team, user, title="Pin latest", products=[product], affected_releases=[floating])

        assert not result.ok
        assert SecurityAdvisory.objects.count() == 0

    def test_foreign_product_rejected_by_the_model_guard(self, team, other_team, user):
        # The service leans on AdvisoryProduct.clean for tenancy, so a direct
        # caller with another workspace's product blows up rather than writing.
        from django.core.exceptions import ValidationError

        foreign = Product.objects.create(name="Not yours", team=other_team)
        with pytest.raises(ValidationError, match="Cross-tenant"):
            create_advisory(team, user, title="x", products=[foreign])
        assert SecurityAdvisory.objects.count() == 0

    def test_release_with_no_version_string_falls_back_to_its_name(self, team, user, product):
        legacy = Release.objects.create(product=product, name="spring-drop", version="")
        result = create_advisory(team, user, title="Legacy", products=[product], affected_releases=[legacy])

        version_range = SecurityAdvisory.objects.get(pk=result.value).vulnerabilities.get().product_statuses.get().version_ranges.get()
        assert version_range.introduced == "spring-drop"


class TestAdvisoryCreateForm:
    def test_rejects_a_release_whose_product_is_not_selected(self, team, product, release):
        other = Product.objects.create(name="Acme Router", team=team)
        form = AdvisoryCreateForm(team, {"title": "x", "products": [other.id], "affected_releases": [release.id]})

        assert not form.is_valid()
        assert "affected_releases" in form.errors

    def test_rejects_another_workspaces_product(self, team, other_team):
        foreign = Product.objects.create(name="Not yours", team=other_team)
        form = AdvisoryCreateForm(team, {"title": "x", "products": [foreign.id]})

        assert not form.is_valid()
        assert "products" in form.errors

    def test_normalises_cve_case(self, team):
        form = AdvisoryCreateForm(team, {"title": "x", "vulnerability_id": "cve-2026-0001"})

        assert form.is_valid()
        assert form.cleaned_data["vulnerability_id"] == "CVE-2026-0001"

    def test_latest_release_is_not_offered_or_accepted(self, team, product):
        floating = Release.objects.create(product=product, name="latest", is_latest=True)
        form = AdvisoryCreateForm(team, {"title": "x", "products": [product.id], "affected_releases": [floating.id]})

        assert not form.is_valid()
        assert all(r["id"] != floating.id for p in creation_options(team).value for r in p["releases"])


class TestDashboardCreatePost:
    def test_post_creates_and_redirects_to_detail(self, sample_team_with_owner_member, product, release, client):
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)

        response = client.post(
            reverse("core:security_advisories_dashboard"),
            {
                "title": "Improper authentication",
                "severity": "critical",
                "vulnerability_id": "CVE-2026-99999",
                "products": [product.id],
                "affected_releases": [release.id],
            },
        )

        advisory = SecurityAdvisory.objects.get()
        assert response.status_code == 302
        assert response.url == reverse("core:security_advisory_detail", args=[advisory.id])
        assert advisory.products.get().product == product

    def test_invalid_post_creates_nothing(self, sample_team_with_owner_member, client):
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)

        response = client.post(reverse("core:security_advisories_dashboard"), {"title": ""})

        assert response.status_code == 302
        assert response.url == reverse("core:security_advisories_dashboard")
        assert SecurityAdvisory.objects.count() == 0

    def test_detail_chip_shows_affected_releases(self, team, user, product, release):
        from sbomify.apps.security_advisories.services.advisories import get_advisory

        result = create_advisory(team, user, title="Chip", products=[product], affected_releases=[release])
        detail = get_advisory(team, result.value).value

        assert detail["products"][0]["affected_ranges"] == ["1.2.0"]

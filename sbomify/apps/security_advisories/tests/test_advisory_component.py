"""Advisories about a component rather than a product.

``AdvisoryProduct`` was the only subject a status could name, so "the auth
library we ship at 1.2.3 is affected" had nowhere to go. That statement is the
one a workspace needs when the same component sits inside several products.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.utils import IntegrityError
from django.utils import timezone

from sbomify.apps.core.models import Component, ComponentRelease, Product
from sbomify.apps.security_advisories.models import (
    AdvisoryComponent,
    AdvisoryProduct,
    AdvisoryProductStatus,
    AdvisoryVersionRange,
    AdvisoryVulnerability,
    SecurityAdvisory,
)
from sbomify.apps.security_advisories.services.release_impact import (
    UNDETERMINED,
    VERSION,
    advisories_affecting_component_release,
)


@pytest.fixture
def team(sample_team_with_owner_member):
    return sample_team_with_owner_member.team


@pytest.fixture
def component(team):
    return Component.objects.create(name="auth-library", team=team)


@pytest.fixture
def advisory(team):
    return SecurityAdvisory.objects.create(
        team=team,
        title="Token comparison is not constant time",
        status=SecurityAdvisory.Status.PUBLISHED,
        tracking_id="QA-SA-2026-0002",
        published_at=timezone.now(),
    )


def _component_range(advisory, component, **bounds):
    vuln = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-0002")
    subject = AdvisoryComponent.objects.create(advisory=advisory, component=component)
    status = AdvisoryProductStatus.objects.create(
        vulnerability=vuln,
        advisory_component=subject,
        status=AdvisoryProductStatus.Status.EXPLOITABLE,
    )
    return AdvisoryVersionRange.objects.create(product_status=status, **bounds)


@pytest.mark.django_db
class TestAdvisoryComponent:
    def test_the_name_is_snapshotted_from_the_component(self, advisory, component):
        subject = AdvisoryComponent.objects.create(advisory=advisory, component=component)
        assert subject.component_name == "auth-library"

    def test_deleting_the_component_leaves_the_advisory_readable(self, advisory, component):
        """Retiring a component must not rewrite security history."""
        subject = AdvisoryComponent.objects.create(advisory=advisory, component=component)
        component.delete()
        subject.refresh_from_db()

        assert subject.component_id is None
        assert subject.component_name == "auth-library"

    def test_a_row_naming_nothing_is_rejected(self, advisory):
        with pytest.raises(ValidationError) as exc:
            AdvisoryComponent.objects.create(advisory=advisory)
        assert "component_name" in exc.value.message_dict

    def test_a_component_from_another_workspace_is_rejected(self, advisory, django_user_model):
        from sbomify.apps.teams.models import Team

        other_team = Team.objects.create(name="Somewhere Else")
        outsider = Component.objects.create(name="theirs", team=other_team)

        with pytest.raises(ValidationError) as exc:
            AdvisoryComponent.objects.create(advisory=advisory, component=outsider)
        assert "component" in exc.value.message_dict

    def test_a_workspace_notice_names_no_components(self, team, component):
        notice = SecurityAdvisory.objects.create(
            team=team,
            title="We looked into it, nothing we ship is affected",
            advisory_type=SecurityAdvisory.AdvisoryType.WORKSPACE_NOTICE,
        )
        with pytest.raises(ValidationError) as exc:
            AdvisoryComponent.objects.create(advisory=notice, component=component)
        assert "advisory" in exc.value.message_dict

    def test_the_same_component_cannot_be_named_twice(self, advisory, component):
        AdvisoryComponent.objects.create(advisory=advisory, component=component)
        # Its own atomic block: the failed constraint poisons the outer one.
        with pytest.raises(IntegrityError), transaction.atomic():
            AdvisoryComponent.objects.create(advisory=advisory, component=component)


@pytest.mark.django_db
class TestStatusSubjects:
    """A status names a product or a component, never both, sometimes neither."""

    def test_naming_both_is_rejected(self, advisory, component):
        vuln = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-0003")
        product = Product.objects.create(name="Lithium", team=advisory.team)
        as_product = AdvisoryProduct.objects.create(advisory=advisory, product=product)
        as_component = AdvisoryComponent.objects.create(advisory=advisory, component=component)

        with pytest.raises(ValidationError) as exc:
            AdvisoryProductStatus.objects.create(
                vulnerability=vuln, advisory_product=as_product, advisory_component=as_component
            )
        assert "advisory_component" in exc.value.message_dict

    def test_a_component_status_is_not_mistaken_for_a_portfolio_one(self, advisory, component, team):
        """Both leave advisory_product null, and only one of them is portfolio-wide."""
        vuln = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-0004")
        second = Component.objects.create(name="crypto-library", team=team)

        AdvisoryProductStatus.objects.create(
            vulnerability=vuln,
            advisory_component=AdvisoryComponent.objects.create(advisory=advisory, component=component),
            status=AdvisoryProductStatus.Status.EXPLOITABLE,
        )
        # Before the constraint narrowed, this second component status collided
        # with the "one portfolio statement per vulnerability" rule.
        AdvisoryProductStatus.objects.create(
            vulnerability=vuln,
            advisory_component=AdvisoryComponent.objects.create(advisory=advisory, component=second),
            status=AdvisoryProductStatus.Status.NOT_AFFECTED,
        )

        assert AdvisoryProductStatus.objects.filter(vulnerability=vuln).count() == 2

    def test_a_component_status_cannot_recommend_a_product_release(self, advisory, component):
        from sbomify.apps.core.models import Release

        vuln = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-0005")
        product = Product.objects.create(name="Lithium", team=advisory.team)
        release = Release.objects.create(product=product, name="v2.0.0", version="2.0.0")

        with pytest.raises(ValidationError) as exc:
            AdvisoryProductStatus.objects.create(
                vulnerability=vuln,
                advisory_component=AdvisoryComponent.objects.create(advisory=advisory, component=component),
                recommended_release=release,
            )
        assert "component status" in str(exc.value.message_dict["recommended_release"])


@pytest.mark.django_db
class TestAdvisoriesAffectingComponentRelease:
    def _release(self, component, version):
        return ComponentRelease.objects.create(component=component, version=version)

    def test_a_component_release_inside_the_range_is_reported(self, advisory, component):
        _component_range(advisory, component, introduced="1.0.0", fixed="2.0.0")

        impacts = advisories_affecting_component_release(self._release(component, "1.2.3"))

        assert [i.advisory.pk for i in impacts] == [advisory.pk]
        assert impacts[0].matched_by == VERSION

    def test_a_component_release_outside_it_is_not(self, advisory, component):
        _component_range(advisory, component, introduced="1.0.0", fixed="2.0.0")

        assert advisories_affecting_component_release(self._release(component, "2.1.0")) == []

    def test_another_components_advisory_does_not_leak_in(self, advisory, component, team):
        other = Component.objects.create(name="unrelated", team=team)
        _component_range(advisory, other, introduced="1.0.0", fixed="2.0.0")

        assert advisories_affecting_component_release(self._release(component, "1.2.3")) == []

    def test_an_uncomparable_version_is_surfaced(self, advisory, component):
        _component_range(advisory, component, introduced="1.0.0", fixed="2.0.0")

        impacts = advisories_affecting_component_release(self._release(component, "nightly-2026-08-25"))

        assert [i.matched_by for i in impacts] == [UNDETERMINED]
        assert not impacts[0].is_certain

    def test_drafts_stay_out_of_outward_facing_answers(self, component, team):
        draft = SecurityAdvisory.objects.create(team=team, title="Not announced", status=SecurityAdvisory.Status.DRAFT)
        _component_range(draft, component, introduced="1.0.0", fixed="2.0.0")
        release = self._release(component, "1.2.3")

        assert advisories_affecting_component_release(release) == []
        assert len(advisories_affecting_component_release(release, published_only=False)) == 1

    def test_a_product_advisory_does_not_answer_for_a_component(self, advisory, component, team):
        """The two subjects are separate; a product statement is not a component one."""
        product = Product.objects.create(name="Lithium", team=team)
        vuln = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-0006")
        status = AdvisoryProductStatus.objects.create(
            vulnerability=vuln,
            advisory_product=AdvisoryProduct.objects.create(advisory=advisory, product=product),
            status=AdvisoryProductStatus.Status.EXPLOITABLE,
        )
        AdvisoryVersionRange.objects.create(product_status=status, introduced="1.0.0", fixed="2.0.0")

        assert advisories_affecting_component_release(self._release(component, "1.2.3")) == []


@pytest.mark.django_db
def test_a_component_status_does_not_read_as_portfolio_wide(vulnerability, advisory, component) -> None:
    """``__str__`` predates advisory_component and fell through to "All products".

    Three subjects now, not two. An operator reading a log line or an admin row
    would see a status scoped to one component presented as covering the whole
    portfolio, which is the one direction that must not be wrong.
    """
    subject = AdvisoryComponent.objects.create(advisory=advisory, component=component)
    scoped = AdvisoryProductStatus.objects.create(vulnerability=vulnerability, advisory_component=subject)
    portfolio = AdvisoryProductStatus.objects.create(vulnerability=vulnerability)

    assert component.name in str(scoped)
    assert "All products" not in str(scoped)
    assert "All products" in str(portfolio)


@pytest.mark.django_db
def test_status_spanning_two_advisories_rejected_for_a_component(vulnerability, team, component) -> None:
    """The component half of a rule the product half already had.

    Validating only advisory_product let a component belonging to another
    advisory through, which is the same mix-up the product check exists to
    stop.
    """
    other = SecurityAdvisory.objects.create(team=team, title="Other")
    other_component = AdvisoryComponent.objects.create(advisory=other, component=component)
    with pytest.raises(ValidationError, match="different advisories"):
        AdvisoryProductStatus.objects.create(vulnerability=vulnerability, advisory_component=other_component)

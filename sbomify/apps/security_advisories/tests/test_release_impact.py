"""Which advisories affect a release.

The question the pins were supposed to answer and could not: they all carried
``related_name="+"``, so nothing could walk from a Release back to an advisory,
and no code outside these tests ever read them.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from sbomify.apps.core.models import Product, Release
from sbomify.apps.security_advisories.models import (
    AdvisoryProduct,
    AdvisoryProductStatus,
    AdvisoryVersionRange,
    AdvisoryVulnerability,
    SecurityAdvisory,
)
from sbomify.apps.security_advisories.services.release_impact import (
    PINNED,
    UNDETERMINED,
    VERSION,
    advisories_affecting_release,
    version_in_range,
)


@pytest.fixture
def product(sample_team_with_owner_member):
    return Product.objects.create(name="Lithium", team=sample_team_with_owner_member.team)


@pytest.fixture
def advisory(sample_team_with_owner_member):
    # published_at and tracking_id are required for PUBLISHED; the model says so.
    return SecurityAdvisory.objects.create(
        team=sample_team_with_owner_member.team,
        title="Session token written to debug logs",
        status=SecurityAdvisory.Status.PUBLISHED,
        tracking_id="QA-SA-2026-0001",
        published_at=timezone.now(),
    )


def _range(advisory, product, **bounds):
    vuln = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-0001")
    advisory_product = AdvisoryProduct.objects.create(advisory=advisory, product=product)
    status = AdvisoryProductStatus.objects.create(
        vulnerability=vuln,
        advisory_product=advisory_product,
        status=AdvisoryProductStatus.Status.EXPLOITABLE,
    )
    return AdvisoryVersionRange.objects.create(product_status=status, **bounds)


def _release(product, name, version):
    return Release.objects.create(product=product, name=name, version=version)


@pytest.mark.django_db
class TestVersionInRange:
    """OSV semantics: introduced inclusive, fixed exclusive, last_affected inclusive."""

    @pytest.mark.parametrize(
        ("version", "bounds", "expected"),
        [
            ("1.5.0", {"introduced": "1.0.0", "fixed": "2.0.0"}, True),
            ("1.0.0", {"introduced": "1.0.0", "fixed": "2.0.0"}, True),  # introduced is inclusive
            ("2.0.0", {"introduced": "1.0.0", "fixed": "2.0.0"}, False),  # fixed is exclusive
            ("0.9.0", {"introduced": "1.0.0", "fixed": "2.0.0"}, False),
            ("2.0.0", {"introduced": "1.0.0", "last_affected": "2.0.0"}, True),  # inclusive
            ("2.0.1", {"introduced": "1.0.0", "last_affected": "2.0.0"}, False),
            ("9.9.9", {"introduced": "1.0.0"}, True),  # open upper bound
            ("0.0.1", {"fixed": "2.0.0"}, True),  # open lower bound
        ],
    )
    def test_bounds(self, advisory, product, version, bounds, expected):
        assert version_in_range(version, _range(advisory, product, **bounds)) is expected

    def test_an_unparseable_release_version_is_undecidable_not_false(self, advisory, product):
        """Saying "not affected" about something nobody could compare is the bad answer."""
        assert version_in_range("2024.wibble", _range(advisory, product, introduced="1.0.0")) is None

    def test_an_unparseable_bound_is_undecidable_too(self, advisory, product):
        assert version_in_range("1.5.0", _range(advisory, product, introduced="not-a-version")) is None


@pytest.mark.django_db
class TestAdvisoriesAffectingRelease:
    def test_a_release_inside_the_range_is_reported(self, advisory, product):
        _range(advisory, product, introduced="1.0.0", fixed="2.0.0")

        impacts = advisories_affecting_release(_release(product, "v1.5.0", "1.5.0"))

        assert [i.advisory.pk for i in impacts] == [advisory.pk]
        assert impacts[0].matched_by == VERSION
        assert impacts[0].is_certain

    def test_a_release_outside_the_range_is_not(self, advisory, product):
        _range(advisory, product, introduced="1.0.0", fixed="2.0.0")

        assert advisories_affecting_release(_release(product, "v2.1.0", "2.1.0")) == []

    def test_a_pinned_release_is_reported_even_when_versions_would_not_parse(self, advisory, product):
        release = _release(product, "nightly", "nightly-2026-08-25")
        advisory_range = _range(advisory, product, introduced="1.0.0")
        advisory_range.introduced_release = release
        advisory_range.save()

        impacts = advisories_affecting_release(release)

        assert [i.matched_by for i in impacts] == [PINNED]

    def test_the_release_that_fixes_it_is_not_affected_by_it(self, advisory, product):
        release = _release(product, "v2.0.0", "2.0.0")
        advisory_range = _range(advisory, product, introduced="1.0.0", fixed="2.0.0")
        advisory_range.fixed_release = release
        advisory_range.save()

        assert advisories_affecting_release(release) == []

    def test_an_uncomparable_version_is_surfaced_not_swallowed(self, advisory, product):
        _range(advisory, product, introduced="1.0.0", fixed="2.0.0")

        impacts = advisories_affecting_release(_release(product, "nightly", "nightly-2026-08-25"))

        assert [i.matched_by for i in impacts] == [UNDETERMINED]
        assert not impacts[0].is_certain
        assert impacts[0].undetermined == ("[1.0.0, 2.0.0)",)

    def test_drafts_stay_out_of_outward_facing_answers(self, product, sample_team_with_owner_member):
        # A real draft, not a published one flipped: the model rejects that,
        # since a draft carries no tracking id and no published_at.
        draft = SecurityAdvisory.objects.create(
            team=sample_team_with_owner_member.team,
            title="Not announced yet",
            status=SecurityAdvisory.Status.DRAFT,
        )
        _range(draft, product, introduced="1.0.0", fixed="2.0.0")
        release = _release(product, "v1.5.0", "1.5.0")

        assert advisories_affecting_release(release) == []
        assert len(advisories_affecting_release(release, published_only=False)) == 1

    def test_another_products_advisory_does_not_leak_in(self, advisory, product, sample_team_with_owner_member):
        other = Product.objects.create(name="Sodium", team=sample_team_with_owner_member.team)
        _range(advisory, other, introduced="1.0.0", fixed="2.0.0")

        assert advisories_affecting_release(_release(product, "v1.5.0", "1.5.0")) == []

    def test_the_reverse_accessors_exist_now(self, advisory, product):
        """The pins were related_name="+", so this walk was impossible."""
        release = _release(product, "v2.0.0", "2.0.0")
        advisory_range = _range(advisory, product, introduced="1.0.0", fixed="2.0.0")
        advisory_range.fixed_release = release
        advisory_range.save()

        assert list(release.advisory_ranges_fixed_here.all()) == [advisory_range]

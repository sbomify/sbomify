from __future__ import annotations

import pytest
from django.utils import timezone

from sbomify.apps.core.models import Product
from sbomify.apps.security_advisories.models import (
    AdvisoryProduct,
    AdvisoryProductStatus,
    AdvisoryVulnerability,
    SecurityAdvisory,
)


@pytest.fixture
def team(sample_team_with_owner_member):
    return sample_team_with_owner_member.team


@pytest.fixture
def other_team():
    """A second workspace, for the cross-tenant guards.

    ``sample_team_with_owner_member.team`` *is* ``sample_team``, so the shared
    fixtures cannot supply two distinct teams.
    """
    from sbomify.apps.core.utils import number_to_random_token
    from sbomify.apps.teams.models import Team

    team = Team.objects.create(name="other workspace")
    team.key = number_to_random_token(team.pk)
    team.save()
    return team


@pytest.fixture
def advisory(team):
    return SecurityAdvisory.objects.create(team=team, title="Log4Shell in Acme Gateway")


@pytest.fixture
def notice(team):
    return SecurityAdvisory.objects.create(
        team=team,
        title="Investigated CVE-2021-44228",
        advisory_type=SecurityAdvisory.AdvisoryType.WORKSPACE_NOTICE,
    )


@pytest.fixture
def product(team):
    return Product.objects.create(name="Acme Gateway", team=team)


@pytest.fixture
def advisory_product(advisory, product):
    return AdvisoryProduct.objects.create(advisory=advisory, product=product)


@pytest.fixture
def vulnerability(advisory):
    return AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2021-44228")


@pytest.fixture
def make_publishable(advisory, advisory_product, vulnerability):
    """An advisory that passes every publish rule, so a test can break one thing."""
    AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        advisory_product=advisory_product,
        status=AdvisoryProductStatus.Status.EXPLOITABLE,
        action_statement="Upgrade to 1.4.3.",
    )
    return advisory


def publish(advisory: SecurityAdvisory, *, visibility: str | None = None) -> SecurityAdvisory:
    """Minimal stand-in for the publish service, which is follow-up work."""
    advisory.status = SecurityAdvisory.Status.PUBLISHED
    advisory.published_at = timezone.now()
    advisory.tracking_id = SecurityAdvisory.allocate_tracking_id(advisory.team)
    if visibility:
        advisory.visibility = visibility
        if visibility == SecurityAdvisory.Visibility.PUBLIC:
            advisory.made_public_at = timezone.now()
    advisory.save()
    return advisory

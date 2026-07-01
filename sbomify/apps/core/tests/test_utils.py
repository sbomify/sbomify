import json
import re
from random import randint

import pytest
from django.http import HttpRequest
from django.template import Context, Template

from sbomify.apps.billing.stripe_pricing_service import StripePricingService
from sbomify.apps.core.utils import (
    generate_id,
    get_client_ip,
    number_to_random_token,
    token_to_number,
)


def test_id_token_conversion():
    for _ in range(100):
        num = randint(0, 10000)  # nosec: B311
        tok = number_to_random_token(num)
        assert isinstance(tok, str)
        assert len(tok) > 6
        assert num == token_to_number(tok)


def test_generate_id():
    id1 = generate_id()
    assert len(id1) == 12
    assert id1[0].isalpha()
    assert id1.isalnum()
    ids = {generate_id() for _ in range(1000)}
    assert len(ids) == 1000


@pytest.mark.django_db
def test_schema_org_metadata_tag(mocker):
    """
    Test that the schema_org_metadata template tag outputs correct schema.org JSON-LD and valid syntax.
    """
    # Mock the Stripe pricing service
    mocker.patch.object(
        StripePricingService,
        "get_all_plans_pricing",
        return_value={
            "business": {"monthly_price_discounted": 199.0, "annual_price_discounted": 1908.0},
            "starter": {"monthly_price_discounted": 49.0, "annual_price_discounted": 499.0},
        },
    )
    # Create a BillingPlan for each plan
    from sbomify.apps.billing.models import BillingPlan

    BillingPlan.objects.create(key="business", name="Business")
    BillingPlan.objects.create(key="starter", name="Starter")

    template = Template("""
    {% load schema_tags %}
    {% schema_org_metadata %}
    """)
    rendered = template.render(Context({}))

    assert "application/ld+json" in rendered
    assert "SBOMify" in rendered
    assert "Business - Monthly" in rendered
    assert "199.0" in rendered
    assert "Business - Annual" in rendered
    assert "1908.0" in rendered
    assert "Starter - Monthly" in rendered
    assert "49.0" in rendered
    assert "Starter - Annual" in rendered
    assert "499.0" in rendered
    # Check JSON structure
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', rendered, re.DOTALL)
    assert match, "No JSON-LD script found"
    data = json.loads(match.group(1))
    assert data["@type"] == "SoftwareApplication"
    assert any(o["name"] == "Business - Monthly" for o in data["offers"])
    assert any(o["name"] == "Starter - Annual" for o in data["offers"])
    # Validate required schema.org fields
    required_fields = ["@context", "@type", "name", "description", "applicationCategory", "operatingSystem", "offers"]
    for field in required_fields:
        assert field in data, f"Missing required schema.org field: {field}"
    # Validate offers structure
    for offer in data["offers"]:
        assert offer["@type"] == "Offer"
        assert "name" in offer
        assert "price" in offer
        assert "priceCurrency" in offer
        assert "priceSpecification" in offer
        ps = offer["priceSpecification"]
        assert ps["@type"] == "UnitPriceSpecification"
        assert "price" in ps
        assert "priceCurrency" in ps
        assert "billingDuration" in ps
        assert "billingIncrement" in ps


def test_get_client_ip_simplified():
    """
    Test get_client_ip simply returns X-Real-IP if present, otherwise REMOTE_ADDR.
    The application trusts the upstream proxy (Caddy) to sanitize these headers.
    """
    request = HttpRequest()

    # 1. X-Real-IP present (from Caddy)
    request.META = {"HTTP_X_REAL_IP": "1.2.3.4", "REMOTE_ADDR": "10.0.0.1"}
    assert get_client_ip(request) == "1.2.3.4"

    # 2. X-Real-IP missing, fallback to REMOTE_ADDR
    request.META = {"REMOTE_ADDR": "10.0.0.1"}
    assert get_client_ip(request) == "10.0.0.1"


@pytest.mark.django_db
class TestAddArtifactToReleaseCrossTeamCheck:
    """Regression tests for the defense-in-depth cross-team check in add_artifact_to_release.

    The primary check lives in the API layer; these tests verify the utility layer
    also enforces the constraint so internal callers cannot bypass it.
    """

    def test_rejects_cross_team_sbom(self, sample_team_with_owner_member):
        from sbomify.apps.core.domain.exceptions import PermissionDeniedError
        from sbomify.apps.core.models import Component, Product, Release
        from sbomify.apps.core.utils import add_artifact_to_release
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.teams.models import Team

        team_a = sample_team_with_owner_member.team
        team_b = Team.objects.create(name="cross-team-sbom-other")

        component_b = Component.objects.create(name="comp-cross-sbom", team=team_b)
        sbom_b = SBOM.objects.create(
            name="sbom-cross",
            component=component_b,
            format="cyclonedx",
            format_version="1.4",
        )

        product_a = Product.objects.create(name="product-cross-sbom", team=team_a)
        release_a = Release.objects.create(product=product_a, name="v1.0.0")

        with pytest.raises(PermissionDeniedError, match="SBOM component team does not match release product team"):
            add_artifact_to_release(release_a, sbom=sbom_b)

    def test_rejects_cross_team_document(self, sample_team_with_owner_member):
        from sbomify.apps.core.domain.exceptions import PermissionDeniedError
        from sbomify.apps.core.models import Component, Product, Release
        from sbomify.apps.core.utils import add_artifact_to_release
        from sbomify.apps.documents.models import Document
        from sbomify.apps.teams.models import Team

        team_a = sample_team_with_owner_member.team
        team_b = Team.objects.create(name="cross-team-doc-other")

        component_b = Component.objects.create(
            name="comp-cross-doc",
            team=team_b,
            component_type=Component.ComponentType.DOCUMENT,
        )
        doc_b = Document.objects.create(
            name="doc-cross",
            component=component_b,
            document_type="specification",
        )

        product_a = Product.objects.create(name="product-cross-doc", team=team_a)
        release_a = Release.objects.create(product=product_a, name="v1.0.0")

        with pytest.raises(PermissionDeniedError, match="Document component team does not match release product team"):
            add_artifact_to_release(release_a, document=doc_b)

    def test_same_team_sbom_succeeds(self, sample_team_with_owner_member):
        from sbomify.apps.core.models import Component, Product, Release
        from sbomify.apps.core.utils import add_artifact_to_release
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="comp-same-team", team=team)
        sbom = SBOM.objects.create(
            name="sbom-same-team",
            component=component,
            format="cyclonedx",
            format_version="1.4",
        )
        product = Product.objects.create(name="product-same-team", team=team)
        release = Release.objects.create(product=product, name="v1.0.0")

        result = add_artifact_to_release(release, sbom=sbom)
        assert result["created"] is True
        assert result["replaced"] is False

    def test_same_team_document_succeeds(self, sample_team_with_owner_member):
        from sbomify.apps.core.models import Component, Product, Release
        from sbomify.apps.core.utils import add_artifact_to_release
        from sbomify.apps.documents.models import Document

        team = sample_team_with_owner_member.team
        component = Component.objects.create(
            name="comp-doc-same-team",
            team=team,
            component_type=Component.ComponentType.DOCUMENT,
        )
        doc = Document.objects.create(
            name="doc-same-team",
            component=component,
            document_type="specification",
        )
        product = Product.objects.create(name="product-doc-same-team", team=team)
        release = Release.objects.create(product=product, name="v1.0.0")

        result = add_artifact_to_release(release, document=doc)
        assert result["created"] is True
        assert result["replaced"] is False


@pytest.mark.django_db
class TestVerifyItemAccessIsDbAuthoritative:
    """verify_item_access must read the role from the DB, never from the mutable
    (possibly stale) session ``user_teams`` cache — a demoted or removed member
    must not keep elevated access until the cache happens to refresh."""

    @staticmethod
    def _request(user, user_teams):
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = user
        request.session = {"user_teams": user_teams}
        return request

    def test_stale_cached_role_does_not_grant_elevated_access(self, sample_team_with_owner_member):
        from sbomify.apps.core.utils import verify_item_access

        member = sample_team_with_owner_member
        team = member.team

        # Demote to guest in the DB; the session cache is stale and still says owner.
        member.role = "guest"
        member.save(update_fields=["role"])
        request = self._request(member.user, {team.key: {"role": "owner"}})

        # Owner/admin-only check is denied based on the live DB role (guest)...
        assert verify_item_access(request, team, ["owner", "admin"]) is False
        # ...while the user's real (guest) access still works.
        assert verify_item_access(request, team, ["guest"]) is True

    def test_stale_cached_role_for_removed_member_is_denied(self, sample_team_with_owner_member):
        from sbomify.apps.core.utils import verify_item_access
        from sbomify.apps.teams.models import Member

        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user

        # Remove the membership (queryset delete leaves the fixture instance intact
        # for teardown); the session cache is stale and still grants owner.
        Member.objects.filter(pk=sample_team_with_owner_member.pk).delete()
        request = self._request(user, {team.key: {"role": "owner"}})

        assert verify_item_access(request, team, ["owner", "admin"]) is False
        assert verify_item_access(request, team, None) is False


@pytest.mark.django_db
def test_release_artifact_replacement_leaves_single_artifact(sample_team_with_owner_member):
    """Replacement produces exactly one artifact of the format — the atomic delete+create
    can't leave the release with the old artifact gone and no replacement, nor a duplicate."""
    from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
    from sbomify.apps.core.utils import add_artifact_to_release
    from sbomify.apps.sboms.models import SBOM

    team = sample_team_with_owner_member.team
    component = Component.objects.create(name="comp-replace", team=team)
    product = Product.objects.create(name="prod-replace", team=team)
    release = Release.objects.create(product=product, name="v1")
    sbom_old = SBOM.objects.create(name="old", component=component, format="cyclonedx", version="1.0", format_version="1.6")
    sbom_new = SBOM.objects.create(name="new", component=component, format="cyclonedx", version="2.0", format_version="1.6")

    add_artifact_to_release(release, sbom=sbom_old)
    result = add_artifact_to_release(release, sbom=sbom_new, allow_replacement=True)

    assert result["replaced"] is True
    artifacts = ReleaseArtifact.objects.filter(release=release, sbom__component=component, sbom__format="cyclonedx")
    assert artifacts.count() == 1
    assert artifacts.first().sbom_id == sbom_new.id

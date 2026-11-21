"""CRA assessment creation uses governance roles and token scopes."""

from collections.abc import Iterator

import pytest
from django.test import Client, override_settings

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.compliance.models import CRAAssessment
from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
from sbomify.apps.core.models import Product
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _disable_billing() -> Iterator[None]:
    with override_settings(BILLING=False):
        yield


@pytest.fixture
def product(sample_team_with_owner_member: Member) -> Product:
    return Product.objects.create(name="Assessment permissions", team=sample_team_with_owner_member.team)


class TestAssessmentCreationPermissions:
    @pytest.mark.parametrize("existing", [False, True])
    @pytest.mark.parametrize(
        "scopes,allowed",
        [
            (["product:manage"], False),
            (["product:*"], False),
            (["cra_assessment:read"], False),
            (["cra_assessment:manage"], True),
            (["cra_assessment:*"], True),
            (["*"], True),
            (None, True),
            ([], False),
        ],
    )
    def test_creation_requires_assessment_scope(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        product: Product,
        scopes: list[str] | None,
        allowed: bool,
        existing: bool,
    ) -> None:
        """Inventory management must not grant a token CRA governance writes."""
        client, token = authenticated_api_client
        token.scopes = scopes
        token.save(update_fields=["scopes"])
        if existing:
            assert get_or_create_assessment(product.pk, token.user, product.team).ok
        response = client.post(f"/api/v1/compliance/cra/product/{product.pk}", **get_api_headers(token))
        assert response.status_code == ((200 if existing else 201) if allowed else 403), response.content
        assert CRAAssessment.objects.filter(product=product).exists() is (existing or allowed)

    @pytest.mark.parametrize("role", ["owner", "admin", "member", "operator", "guest"])
    def test_creation_requires_governance_role(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        product: Product,
        sample_team_with_owner_member: Member,
        role: str,
    ) -> None:
        """Creation must use the same owner/admin tier as the rest of the wizard."""
        sample_team_with_owner_member.role = role
        sample_team_with_owner_member.save(update_fields=["role"])
        client, token = authenticated_api_client
        response = client.post(f"/api/v1/compliance/cra/product/{product.pk}", **get_api_headers(token))
        allowed = role in ("owner", "admin")
        assert response.status_code == (201 if allowed else 403), response.content
        assert CRAAssessment.objects.filter(product=product).exists() is allowed

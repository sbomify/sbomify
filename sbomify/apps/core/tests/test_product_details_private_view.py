"""Tests for the product details private view."""

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Product
from sbomify.apps.sboms.tests.test_views import setup_test_session
from sbomify.apps.teams.models import Member, Team


@pytest.fixture
def team():
    """Create a public team."""
    return Team.objects.create(name="Test Team", is_public=True)


@pytest.fixture
def product(team):
    """Create a public product."""
    return Product.objects.create(name="Test Product", team=team, is_public=True)


@pytest.fixture
def owner_user(team):
    """Create a user with owner membership on the team."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(username="tei_owner", email="tei_owner@example.com", password="test")
    Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
    return user


@pytest.mark.django_db
class TestPrivateViewTeiUrnRendering:
    """Tests for TEI URN display on private (authenticated) product detail pages."""

    def test_tei_urn_shown_on_private_page(self, team, product, owner_user):
        """TEI URN should render on the private product page when TEA is configured."""
        team.tea_enabled = True
        team.custom_domain = "trust.example.com"
        team.custom_domain_validated = True
        team.save()

        client = Client()
        setup_test_session(client, team, owner_user)

        url = reverse("core:product_details", kwargs={"product_id": product.id})
        response = client.get(url)

        assert response.status_code == 200
        expected_urn = f"urn:tei:uuid:trust.example.com:{product.uuid}"
        assert response.context["product_tei"] == expected_urn

    def test_tei_urn_hidden_for_non_public_product(self, team, owner_user):
        """TEI URN should not render for a non-public product even when TEA is configured."""
        team.tea_enabled = True
        team.custom_domain = "trust.example.com"
        team.custom_domain_validated = True
        team.save()

        non_public_product = Product.objects.create(name="Private Product", team=team, is_public=False)

        client = Client()
        setup_test_session(client, team, owner_user)

        url = reverse("core:product_details", kwargs={"product_id": non_public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        assert "urn:tei:uuid:" not in response.content.decode()

    def test_tei_urn_hidden_on_private_page_when_tea_disabled(self, team, product, owner_user):
        """TEI URN should not render on private page when TEA is disabled."""
        team.tea_enabled = False
        team.save()

        client = Client()
        setup_test_session(client, team, owner_user)

        url = reverse("core:product_details", kwargs={"product_id": product.id})
        response = client.get(url)

        assert response.status_code == 200
        assert "urn:tei:uuid:" not in response.content.decode()

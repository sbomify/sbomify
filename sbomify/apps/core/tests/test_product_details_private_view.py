"""Tests for the product details private view."""

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Product
from sbomify.apps.sboms.tests.test_views import setup_test_session
from sbomify.apps.teams.models import Member, Team


@pytest.fixture
def private_team():
    """Create a team for private view testing."""
    return Team.objects.create(name="Private Test Team", is_public=True)


@pytest.fixture
def private_product(private_team):
    """Create a product for private view testing."""
    return Product.objects.create(name="Test Product", team=private_team, is_public=True)


@pytest.fixture
def owner_user(private_team):
    """Create a user with owner membership on the team."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(username="tei_owner", email="tei_owner@example.com", password="test")
    Member.objects.create(user=user, team=private_team, role="owner", is_default_team=True)
    return user


@pytest.mark.django_db
class TestPrivateViewTeiUrnRendering:
    """Tests for TEI URN display on private (authenticated) product detail pages."""

    def test_tei_urn_shown_on_private_page(self, private_team, private_product, owner_user):
        """TEI URN should render on the private product page when TEA is configured."""
        private_team.tea_enabled = True
        private_team.custom_domain = "trust.example.com"
        private_team.custom_domain_validated = True
        private_team.save()

        client = Client()
        setup_test_session(client, private_team, owner_user)

        url = reverse("core:product_details", kwargs={"product_id": private_product.id})
        response = client.get(url)

        assert response.status_code == 200
        expected_urn = f"urn:tei:uuid:trust.example.com:{private_product.id}"
        assert expected_urn in response.content.decode()

    def test_tei_urn_hidden_for_non_public_product(self, private_team, owner_user):
        """TEI URN should not render for a non-public product even when TEA is configured."""
        private_team.tea_enabled = True
        private_team.custom_domain = "trust.example.com"
        private_team.custom_domain_validated = True
        private_team.save()

        non_public_product = Product.objects.create(name="Private Product", team=private_team, is_public=False)

        client = Client()
        setup_test_session(client, private_team, owner_user)

        url = reverse("core:product_details", kwargs={"product_id": non_public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        assert "urn:tei:uuid:" not in response.content.decode()

    def test_tei_urn_hidden_on_private_page_when_tea_disabled(self, private_team, private_product, owner_user):
        """TEI URN should not render on private page when TEA is disabled."""
        private_team.tea_enabled = False
        private_team.save()

        client = Client()
        setup_test_session(client, private_team, owner_user)

        url = reverse("core:product_details", kwargs={"product_id": private_product.id})
        response = client.get(url)

        assert response.status_code == 200
        assert "urn:tei:uuid:" not in response.content.decode()

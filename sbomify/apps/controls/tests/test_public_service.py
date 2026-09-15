from __future__ import annotations

import pytest

from sbomify.apps.controls.models import ControlStatus
from sbomify.apps.controls.services.public_service import (
    get_public_controls,
    get_public_product_controls,
)
from sbomify.apps.controls.services.status_service import upsert_status
from sbomify.apps.core.models import Product


@pytest.fixture
def published_catalog(sample_catalog):
    """A catalogue the workspace has put on its trust center.

    Activating a catalogue and publishing it are two decisions now, so a
    public-surface test has to make the second one explicitly.
    """
    sample_catalog.is_published = True
    sample_catalog.save(update_fields=["is_published"])
    return sample_catalog


@pytest.mark.django_db
class TestGetPublicControls:
    def test_returns_failure_when_no_active_catalog(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = get_public_controls(team)
        assert not result.ok
        assert "No active catalog" in result.error

    def test_returns_summary_with_categories(self, published_catalog, sample_controls, sample_user) -> None:
        team = published_catalog.team
        upsert_status(sample_controls[0], None, ControlStatus.Status.COMPLIANT, sample_user)

        result = get_public_controls(team)
        assert result.ok
        data = result.value
        assert data["catalog"]["name"] == "SOC 2 Type II"
        assert data["catalog"]["version"] == "2024"
        assert data["total"] == 3
        assert data["addressed"] == 1.0
        assert len(data["categories"]) == 2  # Security, Availability


@pytest.mark.django_db
class TestGetPublicProductControls:
    def test_returns_failure_when_no_active_catalog(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        product = Product.objects.create(team=team, name="Test Product")
        result = get_public_product_controls(product)
        assert not result.ok
        assert "No active catalog" in result.error

    def test_product_fallback_to_global(self, published_catalog, sample_controls, sample_user) -> None:
        """Product controls should fall back to global when no product-specific status exists."""
        team = published_catalog.team
        product = Product.objects.create(team=team, name="Test Product")

        # Set global statuses
        upsert_status(sample_controls[0], None, ControlStatus.Status.COMPLIANT, sample_user)
        upsert_status(sample_controls[1], None, ControlStatus.Status.PARTIAL, sample_user)

        result = get_public_product_controls(product)
        assert result.ok
        data = result.value
        assert data["product"]["name"] == "Test Product"
        # Should inherit global statuses: 1 compliant + 0.5 partial = 1.5 out of 3
        assert data["addressed"] == 1.5
        assert data["total"] == 3

    def test_product_overrides_global(self, published_catalog, sample_controls, sample_user) -> None:
        """Product-specific status should take precedence over global."""
        team = published_catalog.team
        product = Product.objects.create(team=team, name="Test Product")

        # Set global status: CC6.1 = compliant
        upsert_status(sample_controls[0], None, ControlStatus.Status.COMPLIANT, sample_user)
        # Set product-specific override: CC6.1 = not_implemented
        upsert_status(sample_controls[0], product, ControlStatus.Status.NOT_IMPLEMENTED, sample_user)

        result = get_public_product_controls(product)
        assert result.ok
        data = result.value
        # Product override means CC6.1 is not_implemented, so addressed = 0
        assert data["addressed"] == 0.0


@pytest.mark.django_db
class TestPublishingIsSeparateFromActivating:
    """The public surface reads is_published, never is_active.

    Tracking a framework internally is not consent to publish a compliance
    score to your customers, and the two used to be the same flag.
    """

    def test_an_active_but_unpublished_catalogue_is_not_public(self, sample_catalog, sample_controls) -> None:
        assert sample_catalog.is_active is True
        assert sample_catalog.is_published is False

        result = get_public_controls(sample_catalog.team)

        assert not result.ok

    def test_a_published_catalogue_is_public(self, published_catalog, sample_controls) -> None:
        assert get_public_controls(published_catalog.team).ok

    def test_unpublishing_takes_it_off_again(self, published_catalog, sample_controls) -> None:
        published_catalog.is_published = False
        published_catalog.save(update_fields=["is_published"])

        assert not get_public_controls(published_catalog.team).ok

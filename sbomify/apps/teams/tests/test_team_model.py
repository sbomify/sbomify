"""Tests for Team model properties and methods."""

import pytest
from django.urls import reverse

from sbomify.apps.teams.models import Team


@pytest.mark.django_db
class TestTeamPublicUrl:
    """Test Team.public_url property."""

    def test_public_team_with_key_returns_url(self):
        """Public team with key should return valid URL."""
        team = Team.objects.create(name="Public Team", is_public=True)
        # Key is auto-generated on save
        
        assert team.public_url is not None
        expected_url = reverse("core:workspace_public", kwargs={"workspace_key": team.key})
        assert team.public_url == expected_url

    def test_private_team_returns_none(self):
        """Private team should return None."""
        team = Team.objects.create(
            name="Private Team",
            billing_plan="business",
            is_public=False
        )
        
        assert team.public_url is None

# Fixtures for team related test cases

from typing import Any, Generator

import pytest
from django.contrib.auth.base_user import AbstractBaseUser

from sbomify.apps.core.tests.fixtures import guest_user, sample_user  # noqa: F401
from sbomify.apps.core.utils import number_to_random_token

from .models import Member, Team


@pytest.fixture
def sample_team() -> Generator[Team, Any, None]:
    team = Team(name="test team")
    team.save()

    team.key = number_to_random_token(team.pk)
    team.save()

    yield team

    team.delete()


# Note: The 3 fixtures below are mutually exclusive, use on of them in a single test as they
# rely on the same user account.
@pytest.fixture
def sample_team_with_owner_member(
    sample_team: Team,
    sample_user: AbstractBaseUser,  # noqa: F811
) -> Generator[Member, Any, None]:
    # First try to get existing membership
    try:
        membership = Member.objects.get(user=sample_user, team=sample_team)
        membership.role = "owner"
        membership.is_default_team = True
        membership.save()
    except Member.DoesNotExist:
        membership = Member(user=sample_user, team=sample_team, role="owner", is_default_team=True)
        membership.save()

    yield membership

    try:
        membership.delete()
    except Member.DoesNotExist:
        pass


@pytest.fixture
def sample_team_with_admin_member(
    sample_team: Team,
    sample_user: AbstractBaseUser,  # noqa: F811
) -> Generator[Member, Any, None]:
    # First try to get existing membership
    try:
        membership = Member.objects.get(user=sample_user, team=sample_team)
        membership.role = "admin"
        membership.save()
    except Member.DoesNotExist:
        membership = Member(user=sample_user, team=sample_team, role="admin")
        membership.save()

    yield membership

    try:
        membership.delete()
    except Member.DoesNotExist:
        pass


@pytest.fixture
def sample_team_with_guest_member(
    sample_team: Team,
    sample_user: AbstractBaseUser,  # noqa: F811
) -> Generator[Member, Any, None]:
    # First try to get existing membership
    try:
        membership = Member.objects.get(user=sample_user, team=sample_team)
        membership.role = "guest"
        membership.save()
    except Member.DoesNotExist:
        membership = Member(user=sample_user, team=sample_team, role="guest")
        membership.save()

    yield membership

    try:
        membership.delete()
    except Member.DoesNotExist:
        pass

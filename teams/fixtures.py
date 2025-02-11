# Fixtures for team related test cases

from typing import Any, Generator

import pytest
from django.contrib.auth.base_user import AbstractBaseUser

from core.tests.fixtures import guest_user, sample_user  # noqa: F401
from core.utils import number_to_random_token

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
    membership = Member(user=sample_user, team=sample_team, role="owner")
    membership.save()

    yield membership

    membership.delete()


@pytest.fixture
def sample_team_with_admin_member(
    sample_team: Team,
    sample_user: AbstractBaseUser,  # noqa: F811
) -> Generator[Member, Any, None]:
    membership = Member(user=sample_user, team=sample_team, role="admin")
    membership.save()

    yield membership

    membership.delete()


@pytest.fixture
def sample_team_with_guest_member(
    sample_team: Team,
    sample_user: AbstractBaseUser,  # noqa: F811
) -> Generator[Member, Any, None]:
    membership = Member(user=sample_user, team=sample_team, role="guest")
    membership.save()

    yield membership

    membership.delete()

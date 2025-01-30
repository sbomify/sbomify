import os
from typing import Any, Generator

import pytest
from django.contrib.auth.base_user import AbstractBaseUser


@pytest.fixture
def sample_user(
    django_user_model: type[AbstractBaseUser],
) -> Generator[AbstractBaseUser, Any, None]:
    """Create a sample user."""
    user = django_user_model(
        username=os.environ["DJANGO_TEST_USER"],
        email=os.environ["DJANGO_TEST_EMAIL"],
        first_name="Test",
        last_name="User",
    )
    user.set_password(os.environ["DJANGO_TEST_PASSWORD"])
    user.save()

    yield user

    user.delete()


@pytest.fixture
def guest_user(django_user_model: type[AbstractBaseUser]) -> Generator[AbstractBaseUser, Any, None]:
    """Create a sample user."""
    user = django_user_model(
        username="guest",
        email="guest@example.com",
        first_name="Guest",
        last_name="User",
    )
    user.set_password("guest")
    user.save()

    yield user

    user.delete()

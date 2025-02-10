import pytest
import pytest_django

# from django.test.utils import setup_test_environment


# @pytest_django.django_db_setup
@pytest.fixture(scope="session", autouse=True)
def tests_init():
    """This only gets executed once."""

    print("tests_init fixture called.")
    # Below gets called automatically by pytest-django
    # setup_test_environment()

    yield None


pytest_plugins = [
   "core.tests.fixtures",
   "teams.fixtures",
   "sboms.tests.fixtures",
]

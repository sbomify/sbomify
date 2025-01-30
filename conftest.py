import pytest

# from django.test.utils import setup_test_environment


@pytest.fixture(scope="session", autouse=True)
def tests_init():
    """This only gets executed once."""

    print("tests_init fixture called.")
    # Below gets called automatically by pytest-django
    # setup_test_environment()

    yield None


pytest_plugins = [
   "core.fixtures",
   "teams.fixtures",
   "sboms.tests.fixtures",
]

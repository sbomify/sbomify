import os
import pytest
import pytest_django
from pathlib import Path
from dotenv import load_dotenv

# from django.test.utils import setup_test_environment


# @pytest_django.django_db_setup
@pytest.fixture(scope="session", autouse=True)
def tests_init():
    """This only gets executed once."""

    print("tests_init fixture called.")
    # Load test environment variables
    test_env_path = Path(__file__).parent / 'test_env'
    if test_env_path.exists():
        print(f"Loading test environment from {test_env_path}")
        load_dotenv(test_env_path)
    else:
        print("Warning: test_env file not found")

    # Below gets called automatically by pytest-django
    # setup_test_environment()

    yield None


pytest_plugins = [
   "sbomify.apps.core.tests.fixtures",
   "sbomify.apps.core.tests.s3_fixtures",
   "sbomify.apps.core.tests.shared_fixtures",
   "sbomify.apps.teams.fixtures",
   "sbomify.apps.sboms.tests.fixtures",
]


@pytest.fixture(scope="module")
def anyio_backend():
    """Configure anyio to use asyncio backend only for async tests."""
    return "asyncio"

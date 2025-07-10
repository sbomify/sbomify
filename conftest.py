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
   "core.tests.fixtures",
   "core.tests.s3_fixtures",
   "core.tests.shared_fixtures",
   "teams.fixtures",
   "sboms.tests.fixtures",
]

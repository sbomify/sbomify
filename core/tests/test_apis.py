import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import Client
from django.urls import reverse
from ninja.testing import TestClient

from core.apis import router
from core.tests.fixtures import guest_user, sample_user  # noqa: F401
from sboms.models import Component, Product, Project
from sboms.tests.fixtures import (  # noqa: F401
    sample_component,
    sample_product,
    sample_project,
)
from teams.fixtures import sample_team  # noqa: F401
from teams.models import Member, Team
from sboms.tests.test_views import setup_test_session

client = TestClient(router)




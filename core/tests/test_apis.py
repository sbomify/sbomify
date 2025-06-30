from ninja.testing import TestClient

from core.apis import router
from core.tests.fixtures import guest_user, sample_user  # noqa: F401
from sboms.tests.fixtures import (  # noqa: F401
    sample_component,
    sample_product,
    sample_project,
)
from teams.fixtures import sample_team  # noqa: F401

client = TestClient(router)

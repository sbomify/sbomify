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


@pytest.mark.django_db
@pytest.mark.parametrize("item_type,model", [
    ("team", Team),
    ("component", Component),
    ("project", Project),
    ("product", Product),
])
def test_rename_item_success(
    item_type: str,
    model: type,
    sample_user: AnonymousUser,
    sample_team: Team,
    sample_component: Component,
    sample_project: Project,
    sample_product: Product,
) -> None:
    """Test successful renaming of different item types with valid permissions."""
    client = Client()

    # Set up session with team access
    setup_test_session(client, sample_team, sample_user)

    # Get the correct identifier for each item type
    item_data = {
        "team": (sample_team.key, "key"),
        "component": (str(sample_component.id), "id"),
        "project": (str(sample_project.id), "id"),
        "product": (str(sample_product.id), "id"),
    }
    item_id, lookup_field = item_data[item_type]

    response = client.patch(
        reverse("api-1:rename_item", kwargs={"item_type": item_type, "item_id": item_id}),
        data={"name": "New Name"},
        content_type="application/json",
    )

    assert response.status_code == 204
    # Use correct lookup field for each model type
    updated_item = model.objects.get(**{lookup_field: item_id})
    assert updated_item.name == "New Name"


@pytest.mark.django_db
@pytest.mark.parametrize("item_type,required_roles", [
    ("team", ["owner"]),
    ("component", ["owner", "admin"]),
    ("project", ["owner", "admin"]),
    ("product", ["owner", "admin"]),
])
def test_rename_item_permission_denied(
    item_type: str,
    required_roles: list[str],
    guest_user: AnonymousUser,
    sample_team: Team,
    sample_component: Component,
    sample_project: Project,
    sample_product: Product,
) -> None:
    """Test renaming items with insufficient permissions returns 403."""
    # Create member with guest role (lowest privileges)
    Member.objects.create(user=guest_user, team=sample_team, role="guest")

    client = Client()

    # Set up session with team access
    setup_test_session(client, sample_team, guest_user)

    item_id = {
        "team": sample_team.key,
        "component": str(sample_component.id),
        "project": str(sample_project.id),
        "product": str(sample_product.id),
    }[item_type]

    response = client.patch(
        reverse("api-1:rename_item", kwargs={"item_type": item_type, "item_id": item_id}),
        data={"name": "New Name"},
        content_type="application/json",
    )

    # All item types should return 403 when user has guest role
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


@pytest.mark.django_db
def test_rename_item_invalid_type(sample_user: AnonymousUser, sample_team: Team) -> None:
    """Test renaming with invalid item type returns 400."""
    client = Client()

    # Create team membership
    Member.objects.create(user=sample_user, team=sample_team, role="owner")

    # Set up session with team access
    setup_test_session(client, sample_team, sample_user)

    response = client.patch(
        reverse("api-1:rename_item", kwargs={"item_type": "invalid_type", "item_id": "123"}),
        data={"name": "New Name"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid item type"}

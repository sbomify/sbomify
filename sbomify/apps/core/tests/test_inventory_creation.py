"""Creation pages retain entered values when validation or the API rejects them."""

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.models import Component, Product
from sbomify.apps.teams.models import Team

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("destination", ["new", "dashboard"])
@pytest.mark.parametrize("name", [" ", "x" * 256])
@pytest.mark.parametrize("kind", ["product", "component"])
def test_invalid_name_keeps_form_values(
    authenticated_web_client: Client, team_with_business_plan: Team, destination: str, name: str, kind: str
) -> None:
    route = f"core:{kind}_new" if destination == "new" else f"core:{kind}s_dashboard"
    data = {"name": name, "description": "Keep these notes", "component_type": "document", "is_global": "on"}
    response = authenticated_web_client.post(reverse(route), data)
    assert response.status_code == 200
    form = response.context["form"]
    assert form.errors["name"]
    assert form["name"].value() == name
    if kind == "product":
        assert form["description"].value() == data["description"]
    else:
        assert form["component_type"].value() == "document"
        assert form["is_global"].value() is True
    model = Product if kind == "product" else Component
    assert not model.objects.filter(team=team_with_business_plan, name=name.strip()).exists()


@pytest.mark.parametrize("kind", ["product", "component"])
def test_api_rejection_keeps_form_values(authenticated_web_client: Client, mocker: MockerFixture, kind: str) -> None:
    create = mocker.patch(
        f"sbomify.apps.core.views.{kind}s_dashboard.create_{kind}",
        return_value=(400, {"detail": "Plan limit reached"}),
    )
    response = authenticated_web_client.post(reverse(f"core:{kind}_new"), {"name": "Example", "component_type": "bom"})
    assert response.status_code == 200
    assert response.context["form"].non_field_errors() == ["Plan limit reached"]
    assert response.context["form"]["name"].value() == "Example"
    create.assert_called_once()


def test_invalid_component_type_is_a_form_error(authenticated_web_client: Client) -> None:
    response = authenticated_web_client.post(reverse("core:component_new"), {"name": "Example", "component_type": "bad"})
    assert response.status_code == 200
    assert response.context["form"].errors["component_type"]


def test_product_description_limit_is_a_form_error(authenticated_web_client: Client) -> None:
    response = authenticated_web_client.post(reverse("core:product_new"), {"name": "Example", "description": "x" * 1001})
    assert response.status_code == 200
    assert response.context["form"].errors["description"]

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Product, Release
from sbomify.apps.teams.models import Member, Team

pytestmark = pytest.mark.django_db


def test_release_form_scopes_products_and_preselects(
    authenticated_web_client: Client, team_with_business_plan: Team
) -> None:
    product = Product.objects.create(team=team_with_business_plan, name="Gateway")
    other = Product.objects.create(team=Team.objects.create(name="Other"), name="Hidden product")
    url = reverse("core:release_new")
    response = authenticated_web_client.get(url, {"product": product.id})
    assert response.status_code == 200
    assert response.context["form"]["product_id"].value() == product.id
    assert other.id not in response.content.decode()
    assert authenticated_web_client.get(url, {"product": other.id}).status_code == 404
    response = authenticated_web_client.post(url, {"product_id": other.id, "name": "Blocked"})
    assert response.context["form"].errors["product_id"]
    assert not Release.objects.filter(product=other, name="Blocked").exists()


@pytest.mark.parametrize("htmx", [False, True])
def test_release_form_creates_and_redirects(
    authenticated_web_client: Client, team_with_business_plan: Team, htmx: bool
) -> None:
    product = Product.objects.create(team=team_with_business_plan, name="Gateway")
    response = authenticated_web_client.post(
        reverse("core:release_new"),
        {
            "product_id": product.id,
            "name": "January",
            "version": "v1.0",
            "description": "Release notes",
            "is_prerelease": "1",
            "created_at": "2026-01-01T10:00",
            "released_at": "2026-01-02T10:00",
        },
        headers={"HX-Request": "true"} if htmx else {},
    )
    release = Release.objects.get(product=product, name="January")
    assert release.version == "v1.0"
    assert release.description == "Release notes"
    assert release.is_prerelease
    assert release.created_at.day == 1 and release.released_at.day == 2
    assert response["HX-Redirect" if htmx else "Location"] == reverse(
        "core:release_details", args=[product.id, release.id]
    )


@pytest.mark.parametrize(
    "invalid", [{"name": " "}, {"name": "latest"}, {"created_at": "not a date"}, {"description": "a" * 1001}]
)
def test_release_form_preserves_invalid_submissions(
    authenticated_web_client: Client, team_with_business_plan: Team, invalid: dict[str, str]
) -> None:
    product = Product.objects.create(team=team_with_business_plan, name="Gateway")
    data = {"product_id": product.id, "name": "January", "version": "v2", "description": "Keep these notes", **invalid}
    response = authenticated_web_client.post(reverse("core:release_new"), data, headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert response.context["form"].errors
    assert response.context["form"]["version"].value() == "v2"
    assert "HX-Redirect" not in response
    assert not Release.objects.filter(product=product, is_latest=False).exists()


def test_release_form_reports_duplicate_without_overwriting(
    authenticated_web_client: Client, team_with_business_plan: Team
) -> None:
    product = Product.objects.create(team=team_with_business_plan, name="Gateway")
    release = Release.objects.create(product=product, name="January", version="v1")
    response = authenticated_web_client.post(
        reverse("core:release_new"), {"product_id": product.id, "name": "January", "version": "v2"}
    )
    assert "already exists" in str(response.context["form"].non_field_errors())
    release.refresh_from_db()
    assert release.version == "v1"


@pytest.mark.parametrize("role", ["owner", "admin", "member", "guest"])
def test_release_form_uses_live_permissions(
    authenticated_web_client: Client, team_with_business_plan: Team, sample_user: Any, role: str
) -> None:
    product = Product.objects.create(team=team_with_business_plan, name="Gateway")
    Member.objects.filter(team=team_with_business_plan, user=sample_user).update(role=role)
    url = reverse("core:release_new")
    response = authenticated_web_client.get(url)
    assert response.status_code == (302 if role == "guest" else 200)
    response = authenticated_web_client.post(url, {"product_id": product.id, "name": "January"})
    assert Release.objects.filter(product=product, name="January").exists() == (role != "guest")


def test_release_form_empty_workspace(authenticated_web_client: Client) -> None:
    response = authenticated_web_client.get(reverse("core:release_new"))
    assert b"Add a product first" in response.content

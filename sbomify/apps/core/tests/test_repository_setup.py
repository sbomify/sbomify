"""Setup credentials must support onboarding without gaining deletion or billing access."""

from datetime import timedelta
from typing import Any

import pytest
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone
from pytest_mock import MockerFixture

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.authz import ALL_ACTIONS, can
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member, Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup_client(sample_team_with_owner_member: Member) -> tuple[Client, Member, str]:
    member = sample_team_with_owner_member
    client = Client()
    setup_authenticated_client_session(client, member.team, member.user)
    return client, member, reverse("core:repository_setup_token", kwargs={"workspace_key": member.team.key})


def test_setup_token_scope_expiry_and_reset(setup_client: tuple[Client, Member, str]) -> None:
    client, member, url = setup_client
    assert client.get(url).status_code == 405
    assert not AccessToken.objects.exists()
    response = client.post(url)
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    first = response.json()
    credential = AccessToken.objects.get(pk=first["id"])
    assert credential.team_id == member.team_id
    assert credential.user_id == member.user_id
    assert credential.expires_at is not None
    assert abs((credential.expires_at - timezone.now() - timedelta(days=7)).total_seconds()) < 10
    assert set(credential.scopes) <= ALL_ACTIONS
    request = RequestFactory().get("/")
    request.user = member.user
    request.session = client.session
    request.access_token_record = credential
    for action in ["product:create", "component:create", "product:set_visibility", "component:manage_publishers"]:
        assert can(request, action, member.team), action
    for action in ["workspace:delete", "component:delete", "member:manage", "billing:manage"]:
        assert not can(request, action, member.team), action

    replacement = client.post(url, {"previous_id": first["id"]})
    assert replacement.status_code == 200
    assert replacement.json()["token"] != first["token"]
    assert not AccessToken.objects.filter(pk=first["id"]).exists()
    assert AccessToken.objects.count() == 1
    # A stale second reset must not revoke the replacement or create another token.
    assert client.post(url, {"previous_id": first["id"]}).status_code == 404
    assert AccessToken.objects.count() == 1


@pytest.mark.parametrize("role", ["member", "guest", "bot"])
def test_setup_token_checks_live_role(setup_client: tuple[Client, Member, str], role: str) -> None:
    client, member, url = setup_client
    Member.objects.filter(pk=member.pk).update(role=role)
    assert client.post(url).status_code == 403
    assert not AccessToken.objects.exists()


def test_setup_token_cannot_target_another_workspace(setup_client: tuple[Client, Member, str]) -> None:
    client, member, url = setup_client
    other = Team.objects.create(name="Other workspace")
    other_url = reverse("core:repository_setup_token", kwargs={"workspace_key": other.key})
    assert client.post(other_url).status_code == 403
    foreign = AccessToken.objects.create(user=member.user, team=other, encoded_token="synthetic", description="Other")
    assert client.post(url, {"previous_id": foreign.pk}).status_code == 404
    assert AccessToken.objects.filter(pk=foreign.pk).exists()
    assert client.post(url, {"previous_id": "bad"}).status_code == 400
    assert AccessToken.objects.count() == 1


def test_setup_token_requires_session_and_csrf(setup_client: tuple[Client, Member, str]) -> None:
    _, member, url = setup_client
    assert Client().post(url).status_code == 302
    csrf_client = Client(enforce_csrf_checks=True)
    setup_authenticated_client_session(csrf_client, member.team, member.user)
    assert csrf_client.post(url).status_code == 403
    assert not AccessToken.objects.exists()


def test_setup_instructions_are_public_without_credentials(client: Client) -> None:
    response = client.get(reverse("core:repository_setup_instructions"))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert b"component_type" in response.content
    assert b"Review" in response.content
    assert not AccessToken.objects.exists()


def test_setup_token_can_create_inventory_and_configure_a_publisher(
    setup_client: tuple[Client, Member, str], ensure_billing_plans: Any, mocker: MockerFixture
) -> None:
    from sbomify.apps.oidc.github_api import ResolvedRepository

    client, member, url = setup_client
    workspace = member.team
    workspace.billing_plan = "business"
    workspace.save(update_fields=["billing_plan"])
    credential = client.post(url).json()
    api = Client(HTTP_AUTHORIZATION=f"Bearer {credential['token']}")
    workspaces = api.get("/api/v1/workspaces/")
    assert workspaces.status_code == 200, workspaces.content
    assert [entry["key"] for entry in workspaces.json()] == [workspace.key]
    usage = api.get("/api/v1/billing/usage/", {"team_key": workspace.key})
    assert usage.status_code == 200, usage.content
    assert api.get("/api/v1/billing/plans/").status_code == 200
    product = api.post("/api/v1/products", {"name": "Example repository"}, content_type="application/json")
    assert product.status_code == 201, product.content
    component = api.post(
        "/api/v1/components", {"name": "uv.lock", "component_type": "bom"}, content_type="application/json"
    )
    assert component.status_code == 201, component.content
    component_id = component.json()["id"]
    attached = api.patch(
        f"/api/v1/products/{product.json()['id']}",
        {"component_ids": [component_id], "is_public": False},
        content_type="application/json",
    )
    assert attached.status_code == 200, attached.content
    visibility = api.patch(
        f"/api/v1/components/{component_id}", {"visibility": "private"}, content_type="application/json"
    )
    assert visibility.status_code == 200, visibility.content
    mocker.patch(
        "sbomify.apps.oidc.services.resolve_repository",
        return_value=ResolvedRepository(
            repository="example/software", repository_owner="example", repository_id=123, repository_owner_id=456
        ),
    )
    publisher = api.post(
        "/api/v1/auth/oidc/github/bindings",
        {"component_id": component_id, "repository": "example/software"},
        content_type="application/json",
    )
    assert publisher.status_code == 201, publisher.content
    assert api.delete(f"/api/v1/components/{component_id}").status_code == 403

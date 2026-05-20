"""Tests for the trusted-publishers UI views.

The HTML rendering is exercised indirectly (assert key strings appear
in the response) so we don't depend on every CSS class. The important
properties are:

* permissions: only owners/admins can list/create/delete
* the GitHub REST resolver is called with the user-supplied slug
* duplicate (org/repo) on the same component is rejected with 409
* delete cascades through to the bot user (transitively, the bot's
  access tokens) via the post_delete signal landed in OIDC-3
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.oidc.github_api import GitHubResolveError, ResolvedRepository
from sbomify.apps.oidc.models import OIDCBinding
from sbomify.apps.oidc.services import provision_bot_user_for_binding
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Team


@pytest.fixture
def component(db, team_with_business_plan: Team) -> Component:
    return Component.objects.create(
        name="Trusted Pubs UI",
        team=team_with_business_plan,
        component_type=Component.ComponentType.BOM,
    )


@pytest.fixture
def authed_client(team_with_business_plan, sample_user):
    """Owner session against the workspace."""
    from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)
    return client


class TestListView:
    @pytest.mark.django_db
    def test_get_renders_empty_state(self, authed_client: Client, component: Component) -> None:
        response = authed_client.get(
            reverse("oidc:trusted_publishers", kwargs={"component_id": component.id})
        )
        assert response.status_code == 200
        assert b"Trusted Publishers" in response.content
        assert b"No trusted publishers yet" in response.content
        # Quick check the help block is in there too
        assert b"id-token: write" in response.content

    @pytest.mark.django_db
    def test_get_lists_existing_bindings(self, authed_client: Client, component: Component, sample_user) -> None:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        ph = User.objects.create_user(username="ph-list", password="x")
        binding = OIDCBinding.objects.create(
            component=component,
            provider=OIDCBinding.PROVIDER_GITHUB,
            repository="acme/widget",
            repository_id=12345,
            repository_owner_id=67890,
            bot_user=ph,
            created_by=sample_user,
        )
        bot = provision_bot_user_for_binding(binding)
        binding.bot_user = bot
        binding.save(update_fields=["bot_user"])

        response = authed_client.get(
            reverse("oidc:trusted_publishers", kwargs={"component_id": component.id})
        )
        assert response.status_code == 200
        assert b"acme/widget" in response.content
        assert b"owner_id=67890" in response.content

    @pytest.mark.django_db
    def test_get_with_no_session_denies(self, component: Component) -> None:
        """Unauthenticated request gets the standard login redirect."""
        client = Client()
        response = client.get(
            reverse("oidc:trusted_publishers", kwargs={"component_id": component.id})
        )
        # LoginRequiredMixin sends to login URL — status 302
        assert response.status_code in (302, 401, 403)


class TestCreate:
    @pytest.mark.django_db
    def test_post_creates_binding_after_resolving_ids(
        self, authed_client: Client, component: Component, mocker
    ) -> None:
        mocker.patch(
            "sbomify.apps.oidc.services.resolve_repository",
            return_value=ResolvedRepository(
                repository="Acme/Widget",
                repository_owner="Acme",
                repository_id=12345,
                repository_owner_id=67890,
            ),
        )
        response = authed_client.post(
            reverse("oidc:trusted_publishers", kwargs={"component_id": component.id}),
            data={"provider": "github", "repository": "acme/widget"},
        )
        assert response.status_code == 200
        binding = OIDCBinding.objects.get(component=component, repository_id=12345)
        assert binding.repository_owner_id == 67890
        assert binding.repository == "acme/widget"  # normalised lowercase
        # Bot user was provisioned (different from the placeholder, which is deleted)
        assert binding.bot_user.username == f"oidc-bot-{binding.id}"

    @pytest.mark.django_db
    def test_post_with_malformed_slug_400(
        self, authed_client: Client, component: Component, mocker
    ) -> None:
        # Form-level validation catches this BEFORE we'd hit the GitHub API,
        # so the resolver isn't called at all.
        called = mocker.patch("sbomify.apps.oidc.services.resolve_repository")
        response = authed_client.post(
            reverse("oidc:trusted_publishers", kwargs={"component_id": component.id}),
            data={"provider": "github", "repository": "no slash"},
        )
        assert response.status_code == 400
        called.assert_not_called()

    @pytest.mark.django_db
    def test_post_when_repo_not_found_returns_error(
        self, authed_client: Client, component: Component, mocker
    ) -> None:
        mocker.patch(
            "sbomify.apps.oidc.services.resolve_repository",
            side_effect=GitHubResolveError("not_found", "Repository 'ghost/repo' was not found."),
        )
        response = authed_client.post(
            reverse("oidc:trusted_publishers", kwargs={"component_id": component.id}),
            data={"provider": "github", "repository": "ghost/repo"},
        )
        assert response.status_code == 400
        assert b"not found" in response.content.lower()

    @pytest.mark.django_db
    def test_duplicate_binding_409(
        self, authed_client: Client, component: Component, mocker, sample_user
    ) -> None:
        # Pre-existing binding
        from django.contrib.auth import get_user_model

        User = get_user_model()
        ph = User.objects.create_user(username="ph-dup", password="x")
        OIDCBinding.objects.create(
            component=component,
            provider=OIDCBinding.PROVIDER_GITHUB,
            repository="acme/widget",
            repository_id=12345,
            repository_owner_id=67890,
            bot_user=ph,
            created_by=sample_user,
        )

        mocker.patch(
            "sbomify.apps.oidc.services.resolve_repository",
            return_value=ResolvedRepository(
                repository="acme/widget",
                repository_owner="acme",
                repository_id=12345,
                repository_owner_id=67890,
            ),
        )
        response = authed_client.post(
            reverse("oidc:trusted_publishers", kwargs={"component_id": component.id}),
            data={"provider": "github", "repository": "acme/widget"},
        )
        assert response.status_code == 409
        assert b"already bound" in response.content


class TestDelete:
    @pytest.mark.django_db
    def test_post_delete_removes_binding_and_revokes_tokens(
        self, authed_client: Client, component: Component, sample_user
    ) -> None:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        ph = User.objects.create_user(username="ph-del", password="x")
        binding = OIDCBinding.objects.create(
            component=component,
            provider=OIDCBinding.PROVIDER_GITHUB,
            repository="acme/widget",
            repository_id=12345,
            repository_owner_id=67890,
            bot_user=ph,
            created_by=sample_user,
        )
        bot = provision_bot_user_for_binding(binding)
        binding.bot_user = bot
        binding.save(update_fields=["bot_user"])

        # Pretend a token was issued via this binding
        AccessToken.objects.create(
            encoded_token="fake-oidc-token",
            description=f"oidc:github:{binding.id}",
            user=bot,
            team=component.team,
        )

        response = authed_client.post(
            reverse(
                "oidc:trusted_publisher_delete",
                kwargs={"component_id": component.id, "binding_id": binding.id},
            )
        )
        assert response.status_code == 200
        assert not OIDCBinding.objects.filter(pk=binding.id).exists()
        # Bot User AND its access tokens cascade (covered by OIDC-3 signal)
        assert not User.objects.filter(username=bot.username).exists()
        assert not AccessToken.objects.filter(description__contains=binding.id).exists()


class TestPermissions:
    @pytest.mark.django_db
    def test_guest_member_blocked(self, component: Component, team_with_business_plan: Team) -> None:
        from django.contrib.auth import get_user_model

        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
        from sbomify.apps.teams.models import Member

        User = get_user_model()
        guest = User.objects.create_user(username="guest-user", password="x")
        Member.objects.create(team=team_with_business_plan, user=guest, role="guest")

        client = Client()
        setup_authenticated_client_session(client, team_with_business_plan, guest)
        response = client.get(
            reverse("oidc:trusted_publishers", kwargs={"component_id": component.id})
        )
        # GuestAccessBlockedMixin redirects guests
        assert response.status_code in (302, 403)

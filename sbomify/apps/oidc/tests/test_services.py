"""Tests for bot-user provisioning and cleanup."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.oidc.models import OIDCBinding
from sbomify.apps.oidc.services import (
    delete_bot_user_for_binding,
    provision_bot_user_for_binding,
)
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Member, Team


def _make_binding(component: Component, *, repo: str = "acme/widget", repo_id: int = 12345, owner_id: int = 67890):
    """Build a binding WITHOUT triggering provisioning yet (bot_user attached after)."""
    User = get_user_model()
    placeholder = User.objects.create_user(username=f"placeholder-{repo_id}", password="x")
    binding = OIDCBinding(
        component=component,
        provider=OIDCBinding.PROVIDER_GITHUB,
        repository=repo,
        repository_id=repo_id,
        repository_owner_id=owner_id,
        bot_user=placeholder,
    )
    binding.save()
    return binding, placeholder


@pytest.fixture
def component(db, team_with_business_plan: Team) -> Component:
    return Component.objects.create(name="OIDC Test", team=team_with_business_plan)


class TestProvision:
    @pytest.mark.django_db
    def test_creates_bot_user_with_unique_username(self, component: Component) -> None:
        binding, _ = _make_binding(component)
        bot = provision_bot_user_for_binding(binding)
        assert bot.username == f"oidc-bot-{binding.id}"
        assert bot.email == f"oidc-bot-{binding.id}@sbomify.local"
        assert bot.is_active is True
        # Unusable password — no human can log in as this account
        assert not bot.has_usable_password()

    @pytest.mark.django_db
    def test_adds_bot_to_components_workspace_with_bot_role(self, component: Component) -> None:
        binding, _ = _make_binding(component)
        bot = provision_bot_user_for_binding(binding)
        membership = Member.objects.get(user=bot, team=component.team)
        assert membership.role == "bot"
        assert membership.is_default_team is False

    @pytest.mark.django_db
    def test_is_idempotent(self, component: Component) -> None:
        binding, _ = _make_binding(component)
        bot1 = provision_bot_user_for_binding(binding)
        bot2 = provision_bot_user_for_binding(binding)
        assert bot1.pk == bot2.pk
        # Still only one Member row
        assert Member.objects.filter(user=bot1, team=component.team).count() == 1

    @pytest.mark.django_db
    def test_two_bindings_get_distinct_bot_users(self, component: Component) -> None:
        b1, _ = _make_binding(component, repo="a/one", repo_id=1, owner_id=10)
        b2, _ = _make_binding(component, repo="b/two", repo_id=2, owner_id=20)
        bot1 = provision_bot_user_for_binding(b1)
        bot2 = provision_bot_user_for_binding(b2)
        assert bot1.username != bot2.username
        # Each binding gets its own audit identity, the whole point of
        # bot-per-binding vs a shared workspace bot.

    @pytest.mark.django_db
    def test_manual_bot_role_assignment_rejected(self, component: Component) -> None:
        """Security regression for P1-H: any path that tries to write
        ``Member.role="bot"`` for a user without an OIDCBinding must fail
        loudly. Defends against a future admin / API accidentally minting
        a privileged bot Member that isn't backed by a real binding.
        """
        from django.core.exceptions import ValidationError
        from django.contrib.auth import get_user_model

        User = get_user_model()
        unrelated_user = User.objects.create_user(username="not-a-bot", password="x")

        member = Member(team=component.team, user=unrelated_user, role="bot")
        with pytest.raises(ValidationError, match="reserved for synthetic OIDC binding"):
            member.save()

    @pytest.mark.django_db
    def test_preexisting_member_row_is_forced_back_to_bot_role(self, component: Component) -> None:
        """Security regression for C-2: a pre-existing bot User with a
        Member row at an elevated role (data integrity error, future
        code path that adds the row first, or interrupted re-provision)
        MUST have its role forced back to ``"bot"``. ``get_or_create``
        silently kept the elevated role; we now use ``update_or_create``
        semantics in services.
        """
        from django.contrib.auth import get_user_model

        binding, _ = _make_binding(component, repo="acme/widget", repo_id=12345, owner_id=67890)
        UserModel = get_user_model()
        # Manually create the bot user with the EXPECTED markers (our
        # bot, but in a half-baked state from a previous interrupted
        # provision), plus a Member row at the wrong role.
        bot_username = f"oidc-bot-{binding.id}"
        bot_email = f"oidc-bot-{binding.id}@sbomify.local"
        bot_user = UserModel.objects.create_user(
            username=bot_username,
            email=bot_email,
            first_name="OIDC",
            last_name="Bot",
            password="x",
        )
        Member.objects.create(team=component.team, user=bot_user, role="owner", is_default_team=False)

        # Now provision — must downgrade to "bot"
        provision_bot_user_for_binding(binding)

        membership = Member.objects.get(team=component.team, user=bot_user)
        assert membership.role == "bot", (
            f"Bot user retained elevated role={membership.role!r}; "
            "update_or_create must force role back to 'bot'."
        )

    @pytest.mark.django_db
    def test_username_collision_with_unrelated_user_is_refused(self, component: Component) -> None:
        """Provisioning MUST refuse to take over a User whose markers
        don't match the OIDC-bot convention. Defends against the (very
        unlikely) case where a real human or other bot has been created
        with a username that happens to collide.
        """
        from django.contrib.auth import get_user_model

        binding, _ = _make_binding(component, repo="acme/widget", repo_id=12345, owner_id=67890)
        UserModel = get_user_model()
        # Same username, but DIFFERENT email + first_name + last_name →
        # not one of our bots.
        bot_username = f"oidc-bot-{binding.id}"
        UserModel.objects.create_user(
            username=bot_username,
            email="real-person@example.com",
            first_name="Alice",
            last_name="Doe",
            password="some-real-password",
        )
        with pytest.raises(RuntimeError, match="bot username collision"):
            provision_bot_user_for_binding(binding)


class TestDeletion:
    @pytest.mark.django_db
    def test_deleting_binding_removes_bot_user(self, component: Component) -> None:
        binding, _ = _make_binding(component)
        bot = provision_bot_user_for_binding(binding)
        binding.bot_user = bot
        binding.save(update_fields=["bot_user"])
        binding_id = binding.id
        username = bot.username

        binding.delete()  # triggers post_delete signal

        User = get_user_model()
        assert not User.objects.filter(username=username).exists()
        # And the bot's Member row went with the User via FK CASCADE
        assert not Member.objects.filter(team=component.team, user__username=username).exists()
        # Idempotent cleanup: calling delete again is fine
        delete_bot_user_for_binding(binding_id)

    @pytest.mark.django_db
    def test_deleting_binding_revokes_issued_access_tokens(self, component: Component) -> None:
        """The whole safety property: binding revocation = credential revocation.

        Any AccessToken row issued via the binding's bot_user has its
        ``user`` FK pointing at that bot. When the bot is deleted as
        part of binding removal, ``user.access_token_set`` cascades.
        """
        binding, _ = _make_binding(component)
        bot = provision_bot_user_for_binding(binding)
        binding.bot_user = bot
        binding.save(update_fields=["bot_user"])
        token1 = AccessToken.objects.create(
            encoded_token="fake-token-1",
            description="oidc-issued",
            user=bot,
            team=component.team,
        )
        token2 = AccessToken.objects.create(
            encoded_token="fake-token-2",
            description="oidc-issued-2",
            user=bot,
            team=component.team,
        )

        binding.delete()

        assert not AccessToken.objects.filter(pk__in=[token1.pk, token2.pk]).exists()

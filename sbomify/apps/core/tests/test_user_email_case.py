"""One account per email address, compared without case.

allauth lowercases the address a sign-in carries and then matches the stored
value exactly, so an account stored as ``Holder@example.com`` was invisible
to it and a sign-in as ``holder@example.com`` made a second account.
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest
from allauth.core.exceptions import ImmediateHttpResponse
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.management import CommandError, call_command
from django.db import IntegrityError, connection, transaction
from django.test import Client, RequestFactory
from django.urls import reverse

from sbomify.apps.core.adapters import CustomSocialAccountAdapter
from sbomify.apps.core.services.account_deletion import soft_delete_user_account
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Invitation, Team

pytestmark = pytest.mark.django_db
User = get_user_model()
CONSTRAINT_NAME = "core_users_email_ci_unique"
migration = importlib.import_module("sbomify.apps.core.migrations.0030_user_email_case_insensitive_unique")


def _user_stored_as(username: str, email: str):
    """An account whose stored address keeps its case, as rows written before the fix do."""
    user = User.objects.create(username=username)
    User.objects.filter(pk=user.pk).update(email=email)
    return User.objects.get(pk=user.pk)


def _has_constraint() -> bool:
    with connection.cursor() as cursor:
        return CONSTRAINT_NAME in connection.introspection.get_constraints(cursor, User._meta.db_table)


@pytest.fixture
def without_constraint():
    constraint = next(c for c in User._meta.constraints if c.name == CONSTRAINT_NAME)
    with connection.schema_editor() as editor:
        editor.remove_constraint(User, constraint)


class _SocialLogin:
    def __init__(self, email: str):
        self.account = type("Account", (), {"provider": "keycloak", "extra_data": {}, "uid": "uid"})()
        self.user = User(email=email)

    def connect(self, request, user):
        self.user = user


def test_saved_address_is_lower_case():
    user = User.objects.create_user(username="holder", email="Holder@Example.com")

    user.refresh_from_db()
    assert user.email == "holder@example.com"


def test_save_leaves_the_address_alone_when_it_is_not_written():
    user = _user_stored_as("holder", "Holder@example.com")

    user.save(update_fields=["email_verified"])

    assert user.email == "Holder@example.com"


def test_address_held_in_other_case_is_refused():
    User.objects.create_user(username="holder", email="holder@example.com")
    other = User.objects.create_user(username="other", email="other@example.com")

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=other.pk).update(email="HOLDER@example.com")


def test_accounts_without_an_address_do_not_collide():
    User.objects.create_user(username="first", email="")
    User.objects.create_user(username="second", email="")

    assert User.objects.filter(email="").count() == 2


def test_sign_in_joins_the_account_stored_in_other_case():
    holder = _user_stored_as("holder", "Holder@example.com")
    sociallogin = _SocialLogin("holder@example.com")

    CustomSocialAccountAdapter().pre_social_login(RequestFactory().get("/"), sociallogin)

    assert sociallogin.user.pk == holder.pk


def test_sign_in_is_refused_when_two_accounts_hold_the_address(without_constraint, mocker):
    first = _user_stored_as("first", "Holder@example.com")
    second = _user_stored_as("second", "HOLDER@example.com")
    inactive = _user_stored_as("inactive", "holder@EXAMPLE.com")
    User.objects.filter(pk=inactive.pk).update(is_active=False)
    sociallogin = _SocialLogin("holder@example.com")
    warning = mocker.patch("sbomify.apps.core.adapters.logger.warning")

    request = RequestFactory().get("/")
    request.user = AnonymousUser()

    with pytest.raises(ImmediateHttpResponse) as refused:
        CustomSocialAccountAdapter().pre_social_login(request, sociallogin)

    assert refused.value.response.status_code == 409
    assert sociallogin.user.pk is None
    assert User.objects.filter(email__iexact="holder@example.com").count() == 3
    warning.assert_called_once_with(
        "Social sign-in refused: accounts %s share one email address", sorted([first.pk, second.pk])
    )


def test_keycloak_migration_refuses_an_address_two_accounts_hold(without_constraint):
    _user_stored_as("first", "Holder@example.com")
    _user_stored_as("second", "HOLDER@example.com")

    with (
        patch("sbomify.apps.core.management.commands.migrate_to_keycloak.KeycloakManager"),
        pytest.raises(CommandError, match="share the email"),
    ):
        call_command("migrate_to_keycloak", "--user-email", "holder@example.com", "--dry-run")


def test_trust_center_invite_answers_when_two_accounts_hold_the_address(
    without_constraint, sample_user, team_with_business_plan
):
    _user_stored_as("first", "Holder@example.com")
    _user_stored_as("second", "HOLDER@example.com")
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    response = client.post(
        reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key}),
        {"action": "invite", "email": "holder@example.com"},
    )

    assert response.status_code == 302


def test_account_deletion_removes_invitations_sent_in_other_case():
    user = User.objects.create_user(username="holder", email="holder@example.com")
    Invitation.objects.create(team=Team.objects.create(name="Other"), email="Holder@Example.com", role="admin")

    with patch("sbomify.apps.core.services.account_deletion._disable_keycloak_user", return_value=True):
        soft_delete_user_account(user)

    assert not Invitation.objects.exists()


def test_migration_lowercases_addresses_and_adds_the_constraint(without_constraint):
    mixed = _user_stored_as("mixed", "Mixed@Example.com")

    with connection.schema_editor() as editor:
        migration.lowercase_emails_and_add_constraint(django_apps, editor)

    mixed.refresh_from_db()
    assert mixed.email == "mixed@example.com"
    assert _has_constraint()


def test_migration_leaves_accounts_that_share_an_address_alone(without_constraint, mocker):
    first = _user_stored_as("first", "Holder@example.com")
    second = _user_stored_as("second", "HOLDER@example.com")
    mixed = _user_stored_as("mixed", "Mixed@Example.com")
    warning = mocker.patch.object(migration.logger, "warning")

    with connection.schema_editor() as editor:
        migration.lowercase_emails_and_add_constraint(django_apps, editor)

    assert User.objects.get(pk=first.pk).email == "Holder@example.com"
    assert User.objects.get(pk=second.pk).email == "HOLDER@example.com"
    assert User.objects.get(pk=mixed.pk).email == "mixed@example.com"
    assert not _has_constraint()
    assert mocker.call("Accounts %s share one email address in different case", [first.pk, second.pk]) in (
        warning.call_args_list
    )

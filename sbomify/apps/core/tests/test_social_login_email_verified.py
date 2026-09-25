"""An email address counts only once the identity provider has confirmed it.

Two things go to a sign-in on the strength of its address alone: an existing
account with that email, and the invitations sent to it. Both wait for the
provider to confirm the address with ``email_verified``.

Sign-ins here run through allauth's whole flow, starting from the response
Keycloak sends, so the claims sit where allauth keeps them.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from unittest.mock import MagicMock, patch

import pytest
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from allauth.core.context import request_context
from allauth.socialaccount.adapter import get_adapter as get_social_adapter
from allauth.socialaccount.helpers import complete_social_login
from allauth.socialaccount.models import SocialAccount
from django.apps import apps
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.middleware import SessionMiddleware
from django.core import mail
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone
from pytest_mock import MockerFixture

from sbomify.apps.core.context_processors import pending_invitations_context
from sbomify.apps.core.keycloak_events import KeycloakEventPoller
from sbomify.apps.core.models import User
from sbomify.apps.core.services.account_deletion import soft_delete_user_account
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.core.views import keycloak_webhook
from sbomify.apps.documents.access_models import AccessRequest
from sbomify.apps.documents.models import Document
from sbomify.apps.teams.models import Invitation, Member, Team
from sbomify.apps.teams.notifications import get_notifications
from sbomify.apps.teams.permissions import check_member_removal
from sbomify.apps.teams.queries import get_pending_invitations_for_user
from sbomify.apps.teams.signals.handlers import _accept_pending_invitations
from sbomify.apps.teams.utils import create_user_team_and_subscription


def _sign_in(email: str, *, verified: bool, sub: str = "new-identity") -> HttpRequest:
    """Sign in with Keycloak as the OpenID Connect callback does, and return the request."""
    request = RequestFactory().get("/")
    SessionMiddleware(lambda r: HttpResponse()).process_request(request)
    MessageMiddleware(lambda r: HttpResponse()).process_request(request)
    request.user = AnonymousUser()
    claims = {"sub": sub, "email": email, "email_verified": verified, "given_name": "Ada", "family_name": "Byron"}
    with request_context(request):
        provider = get_social_adapter().get_provider(request, "keycloak")
        sociallogin = provider.sociallogin_from_response(request, {"userinfo": claims, "id_token": claims})
        sociallogin.state = {"process": "login"}
        complete_social_login(request, sociallogin)
    return request


def _invitee(email_verified: bool, *, with_own_workspace: bool = False) -> User:
    """``with_own_workspace`` stops signing in from auto-accepting, so the path under test does the work."""
    user = User.objects.create_user(username="invitee", email="invitee@example.com", email_verified=email_verified)
    if with_own_workspace:
        Member.objects.create(user=user, team=Team.objects.create(name="Own Workspace"), role="owner")
    return user


def _invite(team: Team, role: str = "member") -> Invitation:
    return Invitation.objects.create(team=team, email="Invitee@example.com", role=role)


def _linked_account() -> User:
    """An account the access-request form made, then linked by its owner's confirmed sign-in.

    allauth records no email address when it links an identity, so this account has no confirmed one on file.
    """
    account = User.objects.create_user(username="linked", email="linked@example.com")
    _sign_in(account.email, verified=True, sub="linked")
    account.refresh_from_db()
    return account


def _take_address(user: User, email: str, how: str) -> None:
    """Add ``email`` on allauth's email page and make it the account's address.

    ``how`` is "primary" to press Make Primary, or "link" for whoever reads the
    mailbox to follow the confirmation link allauth mails there.
    """
    client = Client()
    client.force_login(user)
    client.post(reverse("account_email"), {"action_add": "", "email": email})
    if how == "primary":
        client.post(reverse("account_email"), {"action_primary": "", "email": email})
    else:
        address = EmailAddress.objects.get(user=user, email=email)
        Client().post(reverse("account_confirm_email", args=[EmailConfirmationHMAC(address).key]))
    user.refresh_from_db()


@pytest.mark.django_db
class TestLinkingAnIdentity:
    def test_an_unconfirmed_email_does_not_link_an_existing_account(self) -> None:
        holder = User.objects.create_user(username="holder", email="holder@example.com")

        request = _sign_in(holder.email, verified=False)

        assert not request.user.is_authenticated
        assert not SocialAccount.objects.exists()
        assert list(User.objects.all()) == [holder]
        # allauth mails the address its account-already-exists notice instead.
        assert [m.to for m in mail.outbox] == [[holder.email]]

    def test_a_confirmed_email_links_the_existing_account(self) -> None:
        holder = User.objects.create_user(username="holder", email="holder@example.com")

        request = _sign_in(holder.email, verified=True)

        assert request.user == holder
        assert SocialAccount.objects.get(uid="new-identity").user == holder

    def test_a_confirmed_email_links_the_existing_account_whatever_its_case(self) -> None:
        holder = User.objects.create_user(username="holder", email="Holder@example.com")

        request = _sign_in("holder@example.com", verified=True)

        assert request.user == holder
        assert list(User.objects.all()) == [holder]

    def test_a_confirmed_email_held_by_two_accounts_links_neither(self) -> None:
        for username in ("holder", "other-holder"):
            User.objects.create_user(username=username, email="holder@example.com")

        request = _sign_in("holder@example.com", verified=True)

        assert not request.user.is_authenticated
        assert not SocialAccount.objects.exists()

    def test_a_confirmed_email_does_not_link_an_account_an_unconfirmed_identity_signs_in_to(self) -> None:
        _sign_in("holder@example.com", verified=False, sub="first")
        holder = User.objects.get(email="holder@example.com")

        request = _sign_in(holder.email, verified=True, sub="second")

        assert request.user != holder
        assert list(SocialAccount.objects.filter(user=holder).values_list("uid", flat=True)) == ["first"]

    def test_a_confirmed_email_does_not_link_an_account_with_a_password(self) -> None:
        holder = User.objects.create_user(username="holder", email="holder@example.com", password="chosen-by-someone")

        request = _sign_in(holder.email, verified=True, sub="second")

        assert request.user != holder
        assert not SocialAccount.objects.filter(user=holder).exists()

    def test_a_confirmed_email_links_a_signed_in_account_the_provider_confirmed_it_for(self) -> None:
        holder = User.objects.create_user(
            username="holder", email="holder@example.com", email_verified=True, last_login=timezone.now()
        )

        request = _sign_in(holder.email, verified=True, sub="second")

        assert request.user == holder

    @pytest.mark.parametrize("how", ["primary", "link"])
    def test_a_confirmed_email_does_not_link_an_account_that_took_it_on_the_email_page(self, how: str) -> None:
        holder = _linked_account()
        _take_address(holder, "holder@example.com", how)
        assert holder.email == "holder@example.com"

        request = _sign_in(holder.email, verified=True, sub="second")

        assert request.user != holder
        assert list(SocialAccount.objects.filter(user=holder).values_list("uid", flat=True)) == ["linked"]


@pytest.mark.django_db
class TestRecordingTheConfirmation:
    @pytest.mark.parametrize("verified", [True, False])
    def test_signing_up_records_what_the_provider_said(self, verified: bool) -> None:
        _sign_in("new@example.com", verified=verified)

        assert User.objects.get(email="new@example.com").email_verified is verified

    @pytest.mark.parametrize("verified", [True, False])
    def test_each_login_brings_the_flag_up_to_date(self, verified: bool) -> None:
        user = User.objects.create_user(username="back", email="back@example.com", email_verified=not verified)
        SocialAccount.objects.create(user=user, provider="keycloak", uid="returning")

        _sign_in(user.email, verified=verified, sub="returning")

        user.refresh_from_db()
        assert user.email_verified is verified

    def test_confirming_another_address_does_not_confirm_this_one(self) -> None:
        user = User.objects.create_user(username="moved", email="old@example.com", email_verified=True)
        SocialAccount.objects.create(user=user, provider="keycloak", uid="moved")

        _sign_in("new@example.com", verified=True, sub="moved")

        user.refresh_from_db()
        assert user.email_verified is False

    def test_a_new_address_from_the_event_poller_starts_unconfirmed(self, mocker: MockerFixture) -> None:
        mocker.patch("sbomify.apps.core.keycloak_events.KeycloakManager")
        user = User.objects.create_user(username="mover", email="old@example.com", email_verified=True)
        SocialAccount.objects.create(user=user, provider="keycloak", uid="mover")

        KeycloakEventPoller()._handle_update_profile("mover", {"updated_email": "new@example.com"})

        user.refresh_from_db()
        assert (user.email, user.email_verified) == ("new@example.com", False)

    def test_a_new_address_from_the_webhook_starts_unconfirmed(self) -> None:
        user = User.objects.create_user(username="mover", email="old@example.com", email_verified=True)
        SocialAccount.objects.create(user=user, provider="keycloak", uid="mover")
        event = {"type": "UPDATE_PROFILE", "userId": "mover", "details": {"email": "new@example.com"}}

        keycloak_webhook(RequestFactory().post("/", json.dumps(event), content_type="application/json"))

        user.refresh_from_db()
        assert (user.email, user.email_verified) == ("new@example.com", False)

    @pytest.mark.parametrize(
        ("email", "still_confirmed"),
        [("old@example.com", True), ("Old@Example.com", True), ("new@example.com", False)],
    )
    def test_saving_keeps_the_confirmation_only_for_the_same_address(self, email: str, still_confirmed: bool) -> None:
        user = User.objects.create_user(username="mover", email="old@example.com", email_verified=True)

        user.email = email
        user.save()

        user.refresh_from_db()
        assert user.email_verified is still_confirmed

    @pytest.mark.parametrize("how", ["primary", "link"])
    def test_an_address_taken_on_the_email_page_starts_unconfirmed(self, how: str) -> None:
        user = _linked_account()
        assert user.email_verified is True

        _take_address(user, "new@example.com", how)

        assert (user.email, user.email_verified) == ("new@example.com", False)

    @pytest.mark.parametrize("batch_size", [1, 2000])
    def test_the_backfill_reads_the_claims_each_last_login_stored(
        self, monkeypatch: pytest.MonkeyPatch, batch_size: int
    ) -> None:
        """Logins before this fix recorded False whatever the provider said; the claims they stored were right."""
        cases = {
            "confirmed@example.com": ({"userinfo": {"email": "confirmed@example.com", "email_verified": True}}, True),
            "id-token@example.com": ({"id_token": {"email": "id-token@example.com", "email_verified": True}}, True),
            "unconfirmed@example.com": ({"userinfo": {"email": "unconfirmed@example.com", "email_verified": False}}, False),
            "moved@example.com": ({"userinfo": {"email": "elsewhere@example.com", "email_verified": True}}, False),
        }
        for email, (extra_data, _) in cases.items():
            user = User.objects.create_user(username=email, email=email)
            SocialAccount.objects.create(user=user, provider="keycloak", uid=email, extra_data=extra_data)

        backfill = importlib.import_module("sbomify.apps.core.migrations.0029_user_email_verified_from_last_login")
        monkeypatch.setattr(backfill, "BATCH_SIZE", batch_size)
        backfill.record_email_verified_from_last_login(apps, None)

        assert {u.email: u.email_verified for u in User.objects.all()} == {e: v for e, (_, v) in cases.items()}


@pytest.mark.django_db
class TestInvitations:
    @pytest.mark.parametrize("verified", [True, False])
    def test_an_invited_sign_up_joins_only_with_a_confirmed_email(
        self, ensure_billing_plans: None, verified: bool
    ) -> None:
        team = Team.objects.create(name="Inviting Workspace")
        Invitation.objects.create(team=team, email="newcomer@example.com", role="member")

        request = _sign_in("newcomer@example.com", verified=verified)

        # One workspace either way: the invited one, or a personal one to start in.
        assert Member.objects.filter(user=request.user).count() == 1
        assert Member.objects.filter(user=request.user, team=team).exists() is verified

    @pytest.mark.parametrize("verified", [True, False])
    def test_signing_in_auto_accepts_only_for_a_confirmed_email(self, verified: bool) -> None:
        user = _invitee(verified)
        team = Team.objects.create(name="Inviting Workspace")
        _invite(team)
        request = RequestFactory().get("/")
        request.user = user
        request.session = SessionStore()

        _accept_pending_invitations(user, request)

        assert Member.objects.filter(user=user, team=team).exists() is verified

    @pytest.mark.parametrize("verified", [True, False])
    def test_the_invitation_link_needs_a_confirmed_email(self, client: Client, verified: bool) -> None:
        user = _invitee(verified, with_own_workspace=True)
        team = Team.objects.create(name="Inviting Workspace")
        invitation = _invite(team)
        client.force_login(user)

        client.get(reverse("teams:accept_invite", kwargs={"invite_token": str(invitation.token)}))

        assert Member.objects.filter(user=user, team=team).exists() is verified

    @pytest.mark.parametrize("verified", [True, False])
    def test_accepting_from_settings_needs_a_confirmed_email(self, client: Client, verified: bool) -> None:
        user = _invitee(verified, with_own_workspace=True)
        team = Team.objects.create(name="Inviting Workspace")
        invitation = _invite(team)
        client.force_login(user)

        client.post(reverse("core:accept_user_invitation", kwargs={"invitation_id": invitation.id}))

        assert Member.objects.filter(user=user, team=team).exists() is verified

    @pytest.mark.parametrize("verified", [True, False])
    def test_declining_from_settings_needs_a_confirmed_email(self, client: Client, verified: bool) -> None:
        user = _invitee(verified, with_own_workspace=True)
        invitation = _invite(Team.objects.create(name="Inviting Workspace"))
        client.force_login(user)

        client.post(reverse("core:reject_user_invitation", kwargs={"invitation_id": invitation.id}))

        assert Invitation.objects.filter(pk=invitation.pk).exists() is not verified

    @pytest.mark.parametrize("verified", [True, False])
    @patch("sbomify.apps.documents.views.access_requests.StorageClient")
    def test_signing_the_nda_accepts_only_for_a_confirmed_email(
        self, storage: MagicMock, client: Client, team_with_business_plan: Team, verified: bool
    ) -> None:
        team = team_with_business_plan
        content = b"NDA"
        storage.return_value.get_document_data.return_value = content
        nda = Document.objects.create(
            name="NDA",
            component=team.get_or_create_company_wide_component(),
            document_type=Document.DocumentType.NDA,
            document_filename="nda.pdf",
            content_type="application/pdf",
            file_size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
            source="manual_upload",
        )
        team.branding_info["company_nda_document_id"] = nda.id
        team.save()
        user = _invitee(verified, with_own_workspace=True)
        invitation = _invite(team, role="guest")
        access_request = AccessRequest.objects.create(team=team, user=user, status=AccessRequest.Status.PENDING)
        client.force_login(user)
        session = client.session
        session["pending_invitation_token"] = str(invitation.token)
        session.save()

        client.post(
            reverse("documents:sign_nda", kwargs={"team_key": team.key, "request_id": access_request.id}),
            {"signed_name": "Invitee", "consent": "on"},
        )

        assert Member.objects.filter(user=user, team=team).exists() is verified

    @pytest.mark.parametrize("verified", [True, False])
    def test_only_a_confirmed_email_waits_for_its_invitations_instead_of_a_workspace(
        self, ensure_billing_plans: None, verified: bool
    ) -> None:
        user = _invitee(verified)
        _invite(Team.objects.create(name="Inviting Workspace"))

        created = create_user_team_and_subscription(user)

        assert (created is None) is verified

    @pytest.mark.parametrize("verified", [True, False])
    def test_deleting_an_account_removes_invitations_only_for_a_confirmed_email(self, verified: bool) -> None:
        user = _invitee(verified)
        invitation = _invite(Team.objects.create(name="Inviting Workspace"))

        with patch("sbomify.apps.core.services.account_deletion._disable_keycloak_user", return_value=True):
            soft_delete_user_account(user)

        assert Invitation.objects.filter(pk=invitation.pk).exists() is not verified

    @pytest.mark.parametrize("verified", [True, False])
    def test_an_admin_may_leave_for_an_invitation_only_with_a_confirmed_email(self, verified: bool) -> None:
        admin = _invitee(verified)
        membership = Member.objects.create(user=admin, team=Team.objects.create(name="Current"), role="admin")
        _invite(Team.objects.create(name="Inviting Workspace"))

        assert (check_member_removal(admin, membership) is None) is verified

    @pytest.mark.parametrize("verified", [True, False])
    def test_a_trust_center_invitation_files_a_request_only_for_a_confirmed_account(
        self, client: Client, team_with_business_plan: Team, sample_user: User, verified: bool
    ) -> None:
        invitee = _invitee(verified)
        setup_authenticated_client_session(client, team_with_business_plan, sample_user)

        client.post(
            reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key}),
            {"action": "invite", "email": invitee.email},
        )

        assert Invitation.objects.filter(team=team_with_business_plan, email=invitee.email).exists()
        assert AccessRequest.objects.filter(team=team_with_business_plan, user=invitee).exists() is verified

    @pytest.mark.parametrize("verified", [True, False])
    def test_pending_invitations_are_shown_only_for_a_confirmed_email(self, verified: bool) -> None:
        user = _invitee(verified)
        _invite(Team.objects.create(name="Inviting Workspace"))
        request = RequestFactory().get("/")
        request.user = user
        request.session = SessionStore()

        shown = [
            len(get_pending_invitations_for_user(user)),
            len(get_notifications(request)),
            pending_invitations_context(request)["pending_invitations_count"],
        ]

        assert shown == ([1, 1, 1] if verified else [0, 0, 0])

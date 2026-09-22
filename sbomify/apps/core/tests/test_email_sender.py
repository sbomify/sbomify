"""The From address, across every sender in the app.

Written after production mail went out from ``noreply@sbomify.com`` while the
configured address was ``hello@sbomify.com``, and nothing failed. Twenty send
sites had no assertion on their sender between them, so the only thing standing
behind the setting was that each one remembered to pass it.

These tests are deliberately about the envelope, not the wording: whatever the
templates say, mail must leave with the configured sender and a reply path that
reaches a human.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.core import mail

from sbomify.apps.teams.models import Member, Team


@pytest.fixture
def workspace(db):
    return Team.objects.create(name="Sender Workspace")


def _member(django_user_model, team, username, role="owner"):
    user = django_user_model.objects.create_user(
        username=username, email=f"{username}@test.com", password="password"
    )
    Member.objects.create(user=user, team=team, role=role)
    return user


class TestConfiguredSender:
    def test_the_fallback_in_settings_is_repliable(self):
        """The literal default in settings.py must not be an unattended address.

        Reading the source rather than the loaded value on purpose: the loaded
        value comes from the environment in every environment that sets one, so
        it would never exercise the fallback. The fallback is what a process
        that starts without the variable actually sends as, which is how
        production mail went out from noreply@ for as long as it did.
        """
        import re

        source = (Path(settings.BASE_DIR) / "sbomify" / "settings.py").read_text()
        match = re.search(r'DEFAULT_FROM_EMAIL = os\.environ\.get\(\s*"DEFAULT_FROM_EMAIL",\s*"([^"]+)"', source)
        assert match, "DEFAULT_FROM_EMAIL is no longer read with a literal fallback"
        assert not match.group(1).startswith(("noreply@", "no-reply@"))

    def test_settings_sender_is_not_a_black_hole(self):
        assert not settings.DEFAULT_FROM_EMAIL.startswith("noreply@")
        assert not settings.DEFAULT_FROM_EMAIL.startswith("no-reply@")


SENDER = "sender-under-test@sbomify.com"


class TestEverySenderUsesTheSetting:
    """Each send path, driven end to end, asserting only the envelope."""

    @pytest.fixture(autouse=True)
    def _sender(self, settings):
        """A sender distinct from any default, so a hardcoded address fails."""
        settings.DEFAULT_FROM_EMAIL = SENDER

    def test_onboarding_drip(self, django_user_model, workspace):
        from sbomify.apps.onboarding.models import OnboardingStatus
        from sbomify.apps.onboarding.services import OnboardingEmailService

        user = _member(django_user_model, workspace, "dripuser")
        OnboardingStatus.objects.get_or_create(user=user)

        mail.outbox = []
        OnboardingEmailService.send_welcome_email(user)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].from_email == SENDER
        assert mail.outbox[0].reply_to == ["hello@sbomify.com"]

    def test_owner_invitation_notice(self, django_user_model, workspace):
        from sbomify.apps.teams.services.member_notifications import notify_owners_of_owner_invitation

        _member(django_user_model, workspace, "noticeowner", "owner")
        actor = _member(django_user_model, workspace, "noticeadmin", "admin")

        mail.outbox = []
        notify_owners_of_owner_invitation(workspace, actor, "someone@example.com")

        assert mail.outbox
        for message in mail.outbox:
            assert message.from_email == SENDER

    def test_token_expiry_warning(self, django_user_model, workspace):
        from datetime import timedelta

        from django.utils import timezone

        from sbomify.apps.access_tokens.models import AccessToken
        from sbomify.apps.access_tokens.tasks import warn_expiring_tokens

        user = _member(django_user_model, workspace, "tokenowner")
        token = AccessToken.objects.create(
            user=user,
            team=workspace,
            description="ci token",
            encoded_token="tok-sender-test",
            expires_at=timezone.now() + timedelta(days=5),
        )
        # created_at is auto_now_add, so a freshly made token looks like it was
        # issued for five days. Backdate it, or the sweep skips every threshold
        # that is not shorter than the token's whole lifetime.
        AccessToken.objects.filter(pk=token.pk).update(created_at=token.expires_at - timedelta(days=90))

        mail.outbox = []
        warn_expiring_tokens.fn()

        assert len(mail.outbox) == 1
        assert mail.outbox[0].from_email == SENDER

    def test_document_access_decision(self, django_user_model, workspace):
        from sbomify.apps.documents.access_models import AccessRequest
        from sbomify.apps.documents.services.access_emails import notify_access_rejected

        requester = _member(django_user_model, workspace, "requester", "guest")
        access_request = AccessRequest.objects.create(user=requester, team=workspace)

        mail.outbox = []
        notify_access_rejected(access_request)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].from_email == SENDER
        assert mail.outbox[0].reply_to == ["hello@sbomify.com"]

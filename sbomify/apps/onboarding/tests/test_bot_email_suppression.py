"""Synthetic OIDC bot identities must never receive onboarding emails."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core import mail

from sbomify.apps.oidc.services import BOT_USERNAME_PREFIX, is_synthetic_bot_user
from sbomify.apps.onboarding.models import OnboardingEmail, OnboardingStatus
from sbomify.apps.onboarding.services import OnboardingEmailService

User = get_user_model()

BOT_USERNAME = f"{BOT_USERNAME_PREFIX}ttdlqn73bc8s"
BOT_EMAIL = f"{BOT_USERNAME}@sbomify.local"


def _make_bot_user() -> User:
    return User.objects.create_user(
        username=BOT_USERNAME,
        email=BOT_EMAIL,
        first_name="OIDC",
        last_name="Bot",
    )


def _make_human_user() -> User:
    return User.objects.create_user(
        username="real-person",
        email="person@example.com",
        first_name="Real",
        last_name="Person",
    )


class TestIsSyntheticBotUser:
    def test_matches_bot_username_prefix(self):
        assert is_synthetic_bot_user(User(username=BOT_USERNAME, email="whatever@example.com"))

    def test_matches_non_routable_email_domain(self):
        """Catch the bot even if the username convention ever changes."""
        assert is_synthetic_bot_user(User(username="something-else", email=BOT_EMAIL))

    def test_email_domain_match_is_case_insensitive(self):
        assert is_synthetic_bot_user(User(username="x", email=f"{BOT_USERNAME}@SBOMIFY.LOCAL"))

    def test_does_not_match_human(self):
        assert not is_synthetic_bot_user(User(username="real-person", email="person@example.com"))

    def test_does_not_match_lookalike_domain(self):
        """A real address merely containing the domain must still be mailable."""
        assert not is_synthetic_bot_user(User(username="real", email="person@not-sbomify.local.example.com"))

    def test_handles_blank_fields(self):
        assert not is_synthetic_bot_user(User(username="", email=""))


@pytest.mark.django_db
class TestSignalSkipsBots:
    def test_bot_creation_does_not_create_onboarding_status(self):
        bot = _make_bot_user()
        assert not OnboardingStatus.objects.filter(user=bot).exists()

    def test_bot_creation_queues_no_welcome_email_task(self):
        """Assert on the queue call, not mail.outbox — the task is async, so
        outbox stays empty either way and would pass vacuously."""
        with patch("sbomify.apps.onboarding.tasks.queue_welcome_email") as queue:
            _make_bot_user()
        queue.assert_not_called()

    def test_human_creation_still_queues_welcome_email_task(self):
        with patch("sbomify.apps.onboarding.tasks.queue_welcome_email") as queue:
            human = _make_human_user()
        queue.assert_called_once_with(human)

    def test_human_creation_still_creates_onboarding_status(self):
        """The guard must not suppress onboarding for real users."""
        human = _make_human_user()
        assert OnboardingStatus.objects.filter(user=human).exists()


@pytest.mark.django_db
class TestServiceSuppressesBots:
    """The service is the last gate — it must hold even if a bot slips past the signal."""

    def test_send_welcome_email_refuses_bot(self):
        bot = _make_bot_user()
        mail.outbox.clear()

        assert OnboardingEmailService.send_welcome_email(bot) is False
        assert mail.outbox == []
        assert not OnboardingEmail.objects.filter(user=bot).exists()

    def test_drip_choke_point_refuses_bot(self):
        """All four drip emails route through _send_onboarding_email.

        Called with eligible_check=None so nothing *but* the bot guard can
        stop the send — the drip wrappers' own eligibility rules require
        user_role == "owner", which a bot never is, so testing through them
        would pass with or without the fix.
        """
        bot = _make_bot_user()
        mail.outbox.clear()

        sent = OnboardingEmailService._send_onboarding_email(
            bot,
            email_type=OnboardingEmail.EmailType.QUICK_START,
            template_name="quick_start",
            subject="Your quick start guide - sbomify",
            eligible_check=None,
        )

        assert sent is False
        assert mail.outbox == []
        assert not OnboardingEmail.objects.filter(user=bot).exists()

    def test_drip_choke_point_still_sends_to_human(self):
        """Proves the test above isn't passing for want of a deliverable setup."""
        human = _make_human_user()
        mail.outbox.clear()

        sent = OnboardingEmailService._send_onboarding_email(
            human,
            email_type=OnboardingEmail.EmailType.QUICK_START,
            template_name="quick_start",
            subject="Your quick start guide - sbomify",
            eligible_check=None,
        )

        assert sent is True
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [human.email]

    def test_welcome_email_still_sends_to_human(self):
        """Guard rails must not break the real path."""
        human = _make_human_user()
        mail.outbox.clear()

        assert OnboardingEmailService.send_welcome_email(human) is True
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [human.email]

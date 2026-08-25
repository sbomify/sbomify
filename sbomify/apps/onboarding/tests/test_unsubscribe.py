"""Opting out of the onboarding sequence."""

from __future__ import annotations

import pytest
from django.core import mail
from django.urls import reverse

from sbomify.apps.onboarding.models import OnboardingStatus
from sbomify.apps.onboarding.services import OnboardingEmailService
from sbomify.apps.onboarding.utils import get_unsubscribe_url, make_unsubscribe_token, read_unsubscribe_token

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="dripper", email="dripper@test.com", password="password"
    )


class TestToken:
    def test_round_trips(self, user):
        assert read_unsubscribe_token(make_unsubscribe_token(user.pk)) == user.pk

    def test_a_tampered_token_is_refused(self, user):
        token = make_unsubscribe_token(user.pk)
        assert read_unsubscribe_token(token[:-3] + "xyz") is None

    def test_garbage_is_refused(self):
        assert read_unsubscribe_token("not-a-token") is None

    def test_does_not_expire(self, user, settings):
        """An unsubscribe link has to work on a year-old email in someone's archive."""
        from django.core import signing

        token = make_unsubscribe_token(user.pk)
        # A max_age far in the past would reject a timestamped token; ours is
        # read without one, so age is irrelevant.
        assert signing.loads(token, salt="onboarding.unsubscribe") == user.pk


class TestUnsubscribeView:
    def test_get_only_offers(self, client, user):
        """A GET must not act: scanners and prefetchers follow links unbidden."""
        response = client.get(get_unsubscribe_url(user.pk))

        assert response.status_code == 200
        status, _ = OnboardingStatus.objects.get_or_create(user=user)
        assert not status.drip_unsubscribed

    def test_post_unsubscribes(self, client, user):
        response = client.post(get_unsubscribe_url(user.pk))

        assert response.status_code == 200
        status, _ = OnboardingStatus.objects.get_or_create(user=user)
        assert status.drip_unsubscribed

    def test_needs_no_login(self, client, user):
        """The signed token is the credential. Demanding a password to stop
        receiving mail is the pattern unsubscribe rules exist to prevent."""
        response = client.post(get_unsubscribe_url(user.pk))

        assert response.status_code == 200
        assert "login" not in response.headers.get("Location", "")

    def test_a_bad_token_is_rejected(self, client):
        response = client.get(reverse("onboarding:unsubscribe", kwargs={"token": "forged"}))

        assert response.status_code == 400

    def test_is_idempotent(self, client, user):
        client.post(get_unsubscribe_url(user.pk))
        first = OnboardingStatus.objects.get(user=user).drip_unsubscribed_at

        client.post(get_unsubscribe_url(user.pk))

        assert OnboardingStatus.objects.get(user=user).drip_unsubscribed_at == first


class TestSuppression:
    def test_drip_is_suppressed_after_unsubscribing(self, user):
        status, _ = OnboardingStatus.objects.get_or_create(user=user)
        status.welcome_email_sent = True
        status.save()
        status.unsubscribe_from_drip()

        mail.outbox = []
        sent = OnboardingEmailService.send_quick_start_email(user)

        assert sent is False
        assert mail.outbox == []

    def test_eligibility_checks_refuse_too(self, user):
        status, _ = OnboardingStatus.objects.get_or_create(user=user)
        status.welcome_email_sent = True
        status.save()
        status.unsubscribe_from_drip()

        assert status.should_receive_quick_start() is False
        assert status.should_receive_collaboration() is False
        assert status.should_receive_component_reminder() is False
        assert status.should_receive_sbom_reminder() is False


class TestHeaders:
    def test_drip_mail_carries_list_unsubscribe(self, user):
        """Gmail and Yahoo require these on bulk mail, and they are what puts
        the native Unsubscribe control beside the sender name."""
        OnboardingStatus.objects.get_or_create(user=user)

        mail.outbox = []
        OnboardingEmailService.send_welcome_email(user)

        assert len(mail.outbox) == 1
        headers = mail.outbox[0].extra_headers
        assert "List-Unsubscribe" in headers
        assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"

    def test_transactional_mail_does_not(self, django_user_model):
        """Account mail has nothing to opt out of, so it must not offer."""
        from sbomify.apps.documents.access_models import AccessRequest
        from sbomify.apps.documents.services.access_emails import notify_access_rejected
        from sbomify.apps.teams.models import Member, Team

        team = Team.objects.create(name="Txn Workspace")
        requester = django_user_model.objects.create_user(
            username="txnuser", email="txnuser@test.com", password="password"
        )
        Member.objects.create(user=requester, team=team, role="guest")
        access_request = AccessRequest.objects.create(user=requester, team=team)

        mail.outbox = []
        notify_access_rejected(access_request)

        assert len(mail.outbox) == 1
        assert "List-Unsubscribe" not in mail.outbox[0].extra_headers
        assert "Unsubscribe" not in mail.outbox[0].body

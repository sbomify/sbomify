"""A workspace owner with no OnboardingStatus was stepped over every day.

From staging, the same line on every run of the sequence processor, with the
same count:

    Skipped 4 primary owners with missing OnboardingStatus during sequence processing

The row is created by a signal on user creation, so an owner without one
predates that signal or was made by a path that bypassed it. Either way the
count never converged and the message never said who, so there was nothing an
operator could do with it beyond watch it repeat.

Every other call site in this app reaches for the row with ``get_or_create``.
This one used a bare ``get`` and counted the miss — the outlier, not the rule.

Creating the row changes no mail, which is the property that makes closing the
gap safe rather than a way to spam four long-standing users. A fresh row has
``welcome_email_sent=False`` and all four ``should_receive_*`` predicates gate
on it.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from sbomify.apps.onboarding.models import OnboardingStatus
from sbomify.apps.onboarding.services import OnboardingEmailService
from sbomify.apps.teams.models import Member, Team

User = get_user_model()


@pytest.fixture
def owner_without_status(db):
    """A primary workspace owner whose status row never got created.

    The creation signal fires on user save, so the row has to be deleted after
    the fact to reproduce the state staging is actually in.
    """
    user = User.objects.create_user(username="legacy-owner", email="legacy@example.com")
    team = Team.objects.create(name="Legacy Workspace")
    Member.objects.create(team=team, user=user, role="owner", is_default_team=True)
    OnboardingStatus.objects.filter(user=user).delete()
    return user


@pytest.mark.django_db
class TestTheGapIsClosed:
    def test_the_owner_is_no_longer_skipped(self, owner_without_status) -> None:
        """The defect: this owner was stepped over on every run, forever."""
        OnboardingEmailService.get_users_for_onboarding_sequence()

        assert OnboardingStatus.objects.filter(user=owner_without_status).exists()

    def test_it_converges(self, owner_without_status) -> None:
        """The count has to reach zero rather than be restated daily. A second
        pass must find nothing left to do."""
        OnboardingEmailService.get_users_for_onboarding_sequence()
        before = OnboardingStatus.objects.count()

        OnboardingEmailService.get_users_for_onboarding_sequence()

        assert OnboardingStatus.objects.count() == before


@pytest.mark.django_db
class TestNobodyStartsGettingMail:
    """The property that makes backfilling safe instead of a way to mail four
    long-standing users out of nowhere."""

    def test_the_backfilled_owner_is_queued_for_nothing(self, owner_without_status) -> None:
        results = OnboardingEmailService.get_users_for_onboarding_sequence()

        for email_type, users in results.items():
            assert owner_without_status not in users, f"backfill queued {email_type}"

    def test_the_new_row_has_not_had_a_welcome_email(self, owner_without_status) -> None:
        """This is the field every should_receive_* predicate gates on, so it
        is the reason the assertion above holds."""
        OnboardingEmailService.get_users_for_onboarding_sequence()

        status = OnboardingStatus.objects.get(user=owner_without_status)
        assert status.welcome_email_sent is False

    @pytest.mark.parametrize(
        "predicate",
        [
            "should_receive_quick_start",
            "should_receive_component_reminder",
            "should_receive_sbom_reminder",
            "should_receive_collaboration",
        ],
    )
    def test_every_predicate_declines_a_fresh_row(self, owner_without_status, predicate: str) -> None:
        """Asserted one by one rather than in aggregate: if a future predicate
        stops gating on welcome_email_sent, this is what says so."""
        OnboardingEmailService.get_users_for_onboarding_sequence()

        status = OnboardingStatus.objects.get(user=owner_without_status)
        assert getattr(status, predicate)() is False


@pytest.mark.django_db
class TestOwnersWithAStatusAreUnaffected:
    def test_an_existing_row_is_not_replaced(self) -> None:
        """get_or_create must not reset a real user's onboarding progress."""
        user = User.objects.create_user(username="normal-owner", email="normal@example.com")
        team = Team.objects.create(name="Normal Workspace")
        Member.objects.create(team=team, user=user, role="owner", is_default_team=True)
        status = OnboardingStatus.objects.get(user=user)
        status.welcome_email_sent = True
        status.save()

        OnboardingEmailService.get_users_for_onboarding_sequence()

        status.refresh_from_db()
        assert status.welcome_email_sent is True

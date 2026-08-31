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
gap safe rather than a way to spam four long-standing users — but not for the
reason first claimed here. Three of the four ``should_receive_*`` predicates
gate on ``welcome_email_sent``; ``should_receive_sbom_reminder`` does not, and
is held off instead by ``has_created_component`` defaulting to False. Each is
asserted separately below for that reason, since a single "they all gate on
the flag" assertion would have been false and would have passed anyway.
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
        """The count has to reach zero rather than be restated daily.

        Asserted as "one row was created, and the second pass creates no more"
        rather than "the count did not change between two passes" — the latter
        held just as well against the unfixed code, which created nothing at
        all, so it certified the fix without being able to detect its absence.
        """
        OnboardingEmailService.get_users_for_onboarding_sequence()
        assert OnboardingStatus.objects.filter(user=owner_without_status).count() == 1
        before = OnboardingStatus.objects.count()

        OnboardingEmailService.get_users_for_onboarding_sequence()

        assert OnboardingStatus.objects.count() == before


@pytest.mark.django_db
class TestNobodyStartsGettingMail:
    """The property that makes backfilling safe instead of a way to mail four
    long-standing users out of nowhere.

    Not one property but two, which is the correction this class exists to
    carry: three predicates decline because welcome_email_sent is False, and
    should_receive_sbom_reminder declines because has_created_component is.
    """

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
        """Asserted one by one rather than in aggregate, because they do not all
        decline for the same reason: three gate on welcome_email_sent and
        should_receive_sbom_reminder gates on has_created_component. An
        aggregate assertion would have hidden that, which is exactly what the
        original claim in this file did."""
        OnboardingEmailService.get_users_for_onboarding_sequence()

        status = OnboardingStatus.objects.get(user=owner_without_status)
        assert getattr(status, predicate)() is False

    def test_the_sbom_reminder_is_held_off_by_component_state_not_the_flag(self, owner_without_status) -> None:
        """Pinning the actual reason. Setting welcome_email_sent alone must not
        release it — if a later change carries component state onto a
        backfilled row, this is what says the safety argument no longer
        holds."""
        OnboardingEmailService.get_users_for_onboarding_sequence()

        status = OnboardingStatus.objects.get(user=owner_without_status)
        status.welcome_email_sent = True
        status.save()

        assert status.should_receive_sbom_reminder() is False
        assert status.has_created_component is False


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


@pytest.mark.django_db
class TestBotsAreLeftAlone:
    """A synthetic OIDC bot having no status row is the intended state.

    ``onboarding.signals`` refuses to create one for them, so backfilling here
    would resurrect a row an operator deleted, on every run, and list a bot
    among onboarding users. A legacy binding whose Member still carries
    role="owner"/is_default_team=True reaches this loop today.
    """

    @pytest.fixture
    def bot_owner(self, db):
        bot = User.objects.create_user(username="oidc-bot-legacy", email="oidc-bot-legacy@sbomify.local")
        team = Team.objects.create(name="Bot Workspace")
        Member.objects.create(team=team, user=bot, role="owner", is_default_team=True)
        OnboardingStatus.objects.filter(user=bot).delete()
        return bot

    def test_no_status_row_is_created_for_a_bot(self, bot_owner) -> None:
        OnboardingEmailService.get_users_for_onboarding_sequence()

        assert not OnboardingStatus.objects.filter(user=bot_owner).exists()

    def test_a_bot_is_queued_for_nothing(self, bot_owner) -> None:
        results = OnboardingEmailService.get_users_for_onboarding_sequence()

        for users in results.values():
            assert bot_owner not in users


@pytest.mark.django_db
class TestTheBackfilledRowDatesFromTheAccount:
    """created_at anchors days_since_signup and the drip. Stamping it now would
    show "0 days since signup" on the admin screen for an account years old,
    and would restart the drip at day 0 if welcome_email_sent were ever set."""

    def test_it_matches_the_users_join_date(self, owner_without_status) -> None:
        from datetime import timedelta

        from django.utils import timezone

        long_ago = timezone.now() - timedelta(days=900)
        User.objects.filter(pk=owner_without_status.pk).update(date_joined=long_ago)

        OnboardingEmailService.get_users_for_onboarding_sequence()

        status = OnboardingStatus.objects.get(user=owner_without_status)
        assert abs((status.created_at - long_ago).total_seconds()) < 1

    def test_days_since_signup_is_not_reset_to_zero(self, owner_without_status) -> None:
        from datetime import timedelta

        from django.utils import timezone

        User.objects.filter(pk=owner_without_status.pk).update(date_joined=timezone.now() - timedelta(days=900))

        OnboardingEmailService.get_users_for_onboarding_sequence()

        assert OnboardingStatus.objects.get(user=owner_without_status).days_since_signup > 800

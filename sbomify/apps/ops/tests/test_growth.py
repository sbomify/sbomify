"""Signups over time, and the activation funnel's denominator."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from sbomify.apps.core.models import User
from sbomify.apps.onboarding.models import OnboardingStatus
from sbomify.apps.ops.services.growth import activation_funnel, signups_by_day


@pytest.mark.django_db
class TestSignupsByDay:
    def test_every_day_in_the_window_is_present(self):
        """A quiet day is a zero, not a gap. A gap lets a flat line read as busy."""
        series = signups_by_day(days=30)

        assert len(series) == 30
        assert all(point.count == 0 for point in series)

    def test_days_are_consecutive_and_end_today(self):
        series = signups_by_day(days=7)

        assert series[-1].day == timezone.localdate()
        for earlier, later in zip(series, series[1:]):
            assert later.day - earlier.day == timedelta(days=1)

    def test_a_signup_lands_on_its_own_day(self):
        User.objects.create_user(username="today-person", email="today@example.com", password="x")

        series = signups_by_day(days=7)

        assert series[-1].count == 1
        assert sum(point.count for point in series) == 1

    def test_bots_do_not_appear_in_the_trend(self):
        User.objects.create_user(
            username="oidc-bot-xyz",
            email="oidc-bot-xyz@sbomify.local",
            password="x",
        )

        assert sum(point.count for point in signups_by_day(days=7)) == 0


@pytest.mark.django_db
class TestActivationFunnel:
    def test_the_denominator_excludes_bots(self):
        """The old funnel divided status rows by every User row.

        Bots never get a status row, so counting them in the denominator made
        every completion rate read low by however many bots existed.
        """
        person = User.objects.create_user(username="person", email="person@example.com", password="x")
        User.objects.create_user(
            username="oidc-bot-1",
            email="oidc-bot-1@sbomify.local",
            password="x",
        )
        OnboardingStatus.objects.filter(user=person).update(has_completed_wizard=True)

        steps = activation_funnel()

        assert steps[0].label == "Signed up"
        assert steps[0].count == 1
        assert steps[1].count == 1
        assert steps[1].percent_of_signups == 100.0

    def test_a_person_with_no_status_row_still_signed_up(self):
        """The row is created by a signal, so it is not guaranteed.

        Four live workspace owners had none until they were backfilled.
        Counting status rows dropped them out of "Signed up" and out of the
        denominator, which flattered every rate below.
        """
        person = User.objects.create_user(username="legacy", email="legacy@example.com", password="x")
        OnboardingStatus.objects.filter(user=person).delete()

        steps = activation_funnel()

        assert steps[0].label == "Signed up"
        assert steps[0].count == 1

    def test_the_rates_are_measured_against_everyone_who_signed_up(self):
        """One of two people finished the wizard, so the rate is half.

        Against status rows it would have read 100%, because the person
        without a row vanished from the denominator as well as the numerator.
        """
        finished = User.objects.create_user(username="finished", email="finished@example.com", password="x")
        stalled = User.objects.create_user(username="stalled", email="stalled@example.com", password="x")
        OnboardingStatus.objects.filter(user=finished).update(has_completed_wizard=True)
        OnboardingStatus.objects.filter(user=stalled).delete()

        steps = activation_funnel()

        assert steps[0].count == 2
        assert steps[1].count == 1
        assert steps[1].percent_of_signups == 50.0

    def test_the_upload_step_says_bom_because_that_is_what_the_flag_records(self):
        """has_uploaded_sbom is set by a post_save on the BOM table only.

        A document upload never touches it, and populations.artifact_count
        counts documents, so calling this step "artifact" would put two
        definitions of the word on one page.
        """
        steps = activation_funnel()

        assert [step.label for step in steps] == [
            "Signed up",
            "Finished the wizard",
            "Created a component",
            "Uploaded a BOM",
        ]

    def test_an_empty_install_does_not_divide_by_zero(self):
        steps = activation_funnel()

        assert all(step.percent_of_signups == 0.0 for step in steps)

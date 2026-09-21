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

    def test_an_empty_install_does_not_divide_by_zero(self):
        steps = activation_funnel()

        assert all(step.percent_of_signups == 0.0 for step in steps)

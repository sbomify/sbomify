"""A workspace cannot be pushed over ``max_users`` by two people at once.

``can_add_user_to_team`` counts members and returns a verdict, and a verdict
cannot hold a lock past its own return. Every caller wrote afterwards in a
separate statement, so two invitations accepted at the same moment both read the
same count, both passed, and the workspace went over its limit. This is the same
defect the product and component checks had, in the one resource that check does
not cover.

``user_seat`` holds the workspace row across the count and the write. These tests
hold it to that: the lock is really taken, the verdict still reads correctly, and
two real concurrent acceptances cannot both win the last seat.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from django.db import connection, connections, transaction
from django.test.utils import CaptureQueriesContext

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.teams.models import Member, Team
from sbomify.apps.teams.utils import can_add_user_to_team, user_seat


def _two_seat_team(name: str = "capped") -> Team:
    plan, _ = BillingPlan.objects.get_or_create(
        key="two-seats",
        defaults={"name": "Two Seats", "max_users": 2, "max_products": 10, "max_components": 10},
    )
    BillingPlan.objects.filter(pk=plan.pk).update(max_users=2)
    return Team.objects.create(name=name, billing_plan="two-seats")


@pytest.mark.django_db
class TestTheRowIsActuallyLocked:
    def test_the_count_runs_against_a_locked_workspace_row(self) -> None:
        """Without ``FOR UPDATE`` the rest of this is decoration."""
        team = _two_seat_team()

        with CaptureQueriesContext(connection) as captured:
            with user_seat(team) as (can_add, _):
                assert can_add is True

        locking = [q["sql"] for q in captured if "FOR UPDATE" in q["sql"].upper()]
        assert locking, "user_seat did not lock the workspace row"
        # Asked of the model rather than spelled out, so this keeps testing the
        # lock rather than the table's legacy name.
        assert any(Team._meta.db_table in sql for sql in locking)

    def test_the_verdict_is_the_one_the_unlocked_check_gives(self) -> None:
        """The lock changes when the count is safe to act on, not what it says."""
        team = _two_seat_team()

        with user_seat(team) as (locked_verdict, _):
            pass

        assert locked_verdict == can_add_user_to_team(team)[0]

    def test_an_invite_join_still_allows_the_last_seat(self, sample_user) -> None:
        """``is_joining_via_invite`` deliberately allows ``total == max``, because
        the pending user already occupies a slot. The lock is what makes that
        reasoning hold; it must not change the answer."""
        team = _two_seat_team()
        Member.objects.create(team=team, user=sample_user, role="owner")

        with user_seat(team, is_joining_via_invite=True) as (can_add, _):
            assert can_add is True


@pytest.mark.django_db(transaction=True)
class TestTwoAtOnceCannotBothWin:
    def test_the_last_seat_goes_to_exactly_one_of_them(self, django_user_model: Any) -> None:
        """The defect, reproduced as a race and then held closed.

        One seat is free and two people accept at the same instant. Each thread
        takes the seat the way a real caller does, through ``user_seat``, and
        writes inside the block. Exactly one may succeed.
        """
        team = _two_seat_team("race")
        owner = django_user_model.objects.create_user(username="race-owner", email="o@example.test")
        Member.objects.create(team=team, user=owner, role="owner")
        first = django_user_model.objects.create_user(username="race-a", email="a@example.test")
        second = django_user_model.objects.create_user(username="race-b", email="b@example.test")

        both_ready = threading.Barrier(2, timeout=10)
        admitted: list[str] = []
        lock = threading.Lock()

        def accept(user: Any) -> None:
            try:
                both_ready.wait()
                with user_seat(team) as (can_add, _):
                    if not can_add:
                        return
                    Member.objects.create(team=team, user=user, role="member")
                    with lock:
                        admitted.append(user.username)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=accept, args=(user,)) for user in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        # Asserted before the verdict: a worker still stuck on the row lock would
        # leave `admitted` short, and "exactly one got in" would pass for the
        # wrong reason.
        assert not any(thread.is_alive() for thread in threads), "a worker never finished"
        assert len(admitted) == 1, f"both acceptances won the last seat: {admitted}"
        assert Member.objects.filter(team=team).count() == 2

    def test_without_the_lock_both_would_win(self, django_user_model: Any) -> None:
        """The control. If this also admitted one, the test above would prove
        nothing about the lock and everything about the threads not overlapping.
        """
        team = _two_seat_team("control")
        owner = django_user_model.objects.create_user(username="ctl-owner", email="co@example.test")
        Member.objects.create(team=team, user=owner, role="owner")
        first = django_user_model.objects.create_user(username="ctl-a", email="ca@example.test")
        second = django_user_model.objects.create_user(username="ctl-b", email="cb@example.test")

        counted = threading.Barrier(2, timeout=10)
        admitted: list[str] = []
        lock = threading.Lock()

        def accept_unlocked(user: Any) -> None:
            try:
                # The old shape: count, return a verdict, then write separately.
                can_add, _ = can_add_user_to_team(team)
                counted.wait()  # both have now read the same count
                if not can_add:
                    return
                with transaction.atomic():
                    Member.objects.create(team=team, user=user, role="member")
                with lock:
                    admitted.append(user.username)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=accept_unlocked, args=(user,)) for user in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert not any(thread.is_alive() for thread in threads), "a worker never finished"
        assert len(admitted) == 2, "the unlocked shape was expected to overshoot"
        assert Member.objects.filter(team=team).count() == 3


@pytest.mark.django_db
class TestTheSeatTransitionIsOneStep:
    """Taking a seat and releasing the invitation that reserved it.

    The count is members plus unexpired invitations, so an acceptance that
    creates the membership under the lock but deletes the invitation after it
    leaves a window where one person occupies two seats. A concurrent acceptance
    lands in that window and is refused a seat that is actually free.
    """

    def _accepting_sites(self) -> list[tuple[str, int]]:
        """Every ``user_seat`` block that accepts an invitation, and its line."""
        import pathlib as _pathlib

        root = _pathlib.Path(__file__).resolve().parents[3]
        found: list[tuple[str, int]] = []
        for relative in (
            "apps/core/views/__init__.py",
            "apps/teams/signals/handlers.py",
            "apps/teams/views/__init__.py",
            "apps/documents/views/access_requests.py",
        ):
            path = root / relative
            lines = path.read_text().splitlines()
            for index, line in enumerate(lines):
                if "with user_seat(" not in line:
                    continue
                indent = len(line) - len(line.lstrip())
                end = index + 1
                while end < len(lines):
                    current = lines[end]
                    if current.strip() and (len(current) - len(current.lstrip())) <= indent:
                        break
                    end += 1
                block = lines[index:end]
                # The invite form reserves a seat by creating an invitation
                # rather than accepting one, so it has nothing to release.
                if any("Invitation(" in one for one in block):
                    continue
                found.append((relative, index + 1))
                if not any("invitation.delete()" in one for one in block):
                    raise AssertionError(
                        f"{relative}:{index + 1} takes a seat under the lock but releases the "
                        "invitation outside it, so the seat is double counted in between"
                    )
        return found

    def test_every_acceptance_releases_the_invitation_under_the_lock(self) -> None:
        sites = self._accepting_sites()

        # Four acceptance paths today: the settings page, the login auto-accept,
        # the emailed accept link, and NDA acceptance. If this number changes,
        # a path was added or removed and wants checking rather than updating.
        assert len(sites) == 4, sites

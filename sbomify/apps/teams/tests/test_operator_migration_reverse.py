"""Reversing the operator migration stops before it can strand or re-role anyone.

Undone, it narrows the role constraints back, and no operator row satisfies the
old ones. Moving those rows to another role would widen or drop access without
anyone deciding to, so the reverse refuses instead, before it changes anything.
"""

from importlib import import_module

import pytest
from django.apps import apps
from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError

from sbomify.apps.teams.models import Invitation, Member

migration = import_module("sbomify.apps.teams.migrations.0047_operator_role")

pytestmark = pytest.mark.django_db


def test_the_refusal_is_the_first_step_a_reverse_runs() -> None:
    last = migration.Migration.operations[-1]

    assert isinstance(last, migrations.RunPython)
    assert last.reverse_code is migration.refuse_reverse_while_operators_exist


def test_an_operator_membership_stops_the_reverse(sample_team_with_operator_member) -> None:
    with pytest.raises(IrreversibleError, match="1 operator membership"):
        migration.refuse_reverse_while_operators_exist(apps, None)

    assert Member.objects.filter(role="operator").count() == 1


def test_a_pending_operator_invitation_stops_it_too(sample_team) -> None:
    Invitation.objects.create(team=sample_team, email="ops@example.com", role="operator")

    with pytest.raises(IrreversibleError, match="1 operator invitation"):
        migration.refuse_reverse_while_operators_exist(apps, None)


def test_with_no_operator_on_file_the_reverse_goes_ahead(sample_team_with_owner_member) -> None:
    migration.refuse_reverse_while_operators_exist(apps, None)

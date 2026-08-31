"""The database refuses roles the code does not know about.

``role="member"`` existed in the database for years without existing in the code:
``choices`` is not enforced by PostgreSQL and ``Member.save()`` skips
``full_clean()``, so the value was written happily and matched no role check.
Promoting it to a real role fixes that one instance; the constraint is what stops
the next one.

Note these tests need real migrations. The suite runs with ``--nomigrations``,
which builds the schema straight from the models — constraints included — so the
CheckConstraint is present either way.
"""

import os

import pytest
from django.conf import settings
from django.db import IntegrityError, transaction

from sbomify.apps.core.authz import ROLE_MEMBER
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import Invitation, Member, Team


@pytest.mark.django_db
class TestRoleIntegrity:
    def test_database_rejects_an_unrecognised_role(self, django_user_model):
        """The whole point: this write used to succeed."""
        team = Team.objects.create(name="Constraint Workspace")
        user = django_user_model.objects.create_user(username="ghost-role-user", password="x")  # noqa: S106

        with pytest.raises(IntegrityError), transaction.atomic():
            Member.objects.create(team=team, user=user, role="viewer")

    def test_database_rejects_an_unrecognised_role_via_bulk_create(self, django_user_model):
        """bulk_create() bypasses save() and full_clean() — the constraint does not."""
        team = Team.objects.create(name="Bulk Constraint Workspace")
        user = django_user_model.objects.create_user(username="bulk-ghost-user", password="x")  # noqa: S106

        with pytest.raises(IntegrityError), transaction.atomic():
            Member.objects.bulk_create([Member(team=team, user=user, role="superuser")])

    def test_member_is_now_a_real_role(self, django_user_model):
        """The value that started all this is accepted, because it means something."""
        team = Team.objects.create(name="Member Workspace")
        user = django_user_model.objects.create_user(username="real-member-user", password="x")  # noqa: S106

        membership = Member.objects.create(team=team, user=user, role=ROLE_MEMBER)

        assert membership.role == ROLE_MEMBER
        assert ROLE_MEMBER in [role for role, _label in settings.TEAMS_SUPPORTED_ROLES]

    def test_database_rejects_an_unrecognised_invitation_role(self):
        """Invitation was the remaining way in for a role the code doesn't know.

        It was constrained against ``bot`` only, so any other unrecognised value
        was insertable — and an invitation is a deferred Member row, so the bad
        value sat there until accept time and then failed against
        member_role_is_supported, turning a write nobody validated into an
        IntegrityError for whoever clicked the link.
        """
        team = Team.objects.create(name="Invitation Constraint Workspace")

        with pytest.raises(IntegrityError), transaction.atomic():
            Invitation.objects.create(team=team, email="someone@example.com", role="viewer")

    def test_invitations_still_cannot_carry_the_bot_role(self):
        """The invitable set subsumes the old not-bot rule; prove it still holds."""
        team = Team.objects.create(name="Bot Invitation Workspace")

        with pytest.raises(IntegrityError), transaction.atomic():
            Invitation.objects.create(team=team, email="ci@example.com", role="bot")

    def test_every_supported_role_is_writable(self, django_user_model):
        """The constraint must admit exactly the canonical set — no more, no less.

        Scope, precisely: the suite runs with ``--nomigrations`` (see the module
        docstring), so the schema — constraint included — is built from the
        models, which read ``TEAMS_SUPPORTED_ROLES``. That makes this a check of
        model/settings coherence, NOT of migration coherence: a role added to
        settings without a migration would still pass here, because the
        constraint under test was generated from the same setting.
        ``test_models_and_migrations_agree`` is what covers that gap.
        """
        team = Team.objects.create(name="All Roles Workspace")
        for index, (role, _label) in enumerate(settings.TEAMS_SUPPORTED_ROLES):
            user = django_user_model.objects.create_user(username=f"role-{index}-user", password="x")  # noqa: S106
            member = Member(team=team, user=user, role=role)
            if role == "bot":
                # Provisioning a bot is guarded by a pre_save signal that only
                # the OIDC binding flow satisfies.
                member._is_oidc_bot_provisioning = True
            member.save()
            assert Member.objects.filter(team=team, user=user, role=role).exists()


def test_models_and_migrations_agree():
    """No model change is left without a migration.

    ``--nomigrations`` builds the test schema straight from the models, so every
    constraint test in this file passes whether or not the migration history
    describes the same thing — which is the mismatch that actually hurts, since
    production's schema comes from the migrations alone.

    Run in a SUBPROCESS on purpose. ``--nomigrations`` works by patching the
    migration loader for the whole session, so calling ``makemigrations --check``
    in-process reports "no changes" no matter how far the models have drifted —
    the first version of this test did exactly that and passed against a role
    deliberately added without a migration. A fresh interpreter has no such
    patch, and ``--check`` compares models to the migration files on disk rather
    than to a database, so it needs no test DB.
    """
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[4]
    result = subprocess.run(  # noqa: S603
        [sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "sbomify.test_settings"},
    )
    assert result.returncode == 0, (
        "Models have changes with no migration. Run `manage.py makemigrations`.\n"
        f"{result.stdout}\n{result.stderr}"
    )

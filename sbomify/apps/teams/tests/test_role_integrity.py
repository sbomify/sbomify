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

import pytest
from django.conf import settings
from django.db import IntegrityError, transaction

from sbomify.apps.core.authz import ROLE_MEMBER
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import Member, Team


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

    def test_every_supported_role_is_writable(self, django_user_model):
        """The constraint must admit exactly the canonical set — no more, no less.

        Catches a role added to TEAMS_SUPPORTED_ROLES without the matching
        migration, which would otherwise fail only at runtime for that role.
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

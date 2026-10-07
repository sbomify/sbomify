"""Add the ``operator`` role: read the workspace, rule on its vulnerabilities.

Purely additive. No existing row changes role, and no existing role loses
anything: ``operator`` is a new value slotted between ``guest`` and ``member`` on
the ladder, so the only work here is widening the two CheckConstraints that pin
the role sets at the database.

The constraints are dropped and re-added rather than altered because PostgreSQL
has no ALTER CONSTRAINT for a CHECK predicate. Both are widenings, so every
existing row satisfies the new predicate and the re-add validates without a
rewrite.

Reversing narrows them back, and no operator membership or invitation would
satisfy the old predicates. Mapping those rows to another role would silently
widen access (member) or drop it (guest), so the reverse refuses to start while
any exist and names what to reassign first. It runs before anything else is
undone, and the migration is atomic, so a refusal leaves the database as it was.
"""

from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError

# Frozen deliberately, NOT read from settings.TEAMS_SUPPORTED_ROLES — the same
# reason migration 0041 froze its list. A historical migration must describe the
# world as it was at this point in history, or a later release adding a role
# would silently change what this one wrote.
SUPPORTED_ROLES = ["owner", "admin", "member", "operator", "guest", "bot"]
INVITABLE_ROLES = ["owner", "admin", "member", "operator", "guest"]

LABELS = {
    "owner": "Owner",
    "admin": "Admin",
    "member": "Member",
    "operator": "Operator",
    "guest": "Guest",
    "bot": "Bot",
}
MEMBER_CHOICES = [(role, LABELS[role]) for role in SUPPORTED_ROLES]
INVITATION_CHOICES = [(role, LABELS[role]) for role in INVITABLE_ROLES]


def refuse_reverse_while_operators_exist(apps, schema_editor):
    """Stop the reverse while a row still holds the role it is about to forbid."""
    members = apps.get_model("teams", "Member").objects.filter(role="operator").count()
    invitations = apps.get_model("teams", "Invitation").objects.filter(role="operator").count()
    if members or invitations:
        raise IrreversibleError(
            f"Cannot reverse teams.0047: {members} operator membership(s) and {invitations} operator "
            "invitation(s) exist. Give each a role that existed before this migration, or remove it, "
            "then reverse again."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("teams", "0046_invitation_invited_by"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invitation",
            name="role",
            field=models.CharField(choices=INVITATION_CHOICES, max_length=255),
        ),
        migrations.AlterField(
            model_name="member",
            name="role",
            field=models.CharField(choices=MEMBER_CHOICES, max_length=255),
        ),
        migrations.RemoveConstraint(
            model_name="member",
            name="member_role_is_supported",
        ),
        migrations.AddConstraint(
            model_name="member",
            constraint=models.CheckConstraint(
                condition=models.Q(("role__in", SUPPORTED_ROLES)),
                name="member_role_is_supported",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="invitation",
            name="invitation_role_is_invitable",
        ),
        migrations.AddConstraint(
            model_name="invitation",
            constraint=models.CheckConstraint(
                condition=models.Q(("role__in", INVITABLE_ROLES)),
                name="invitation_role_is_invitable",
            ),
        ),
        # Last, so it is the first step a reverse runs.
        migrations.RunPython(migrations.RunPython.noop, refuse_reverse_while_operators_exist),
    ]

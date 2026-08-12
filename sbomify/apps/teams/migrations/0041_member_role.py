"""Promote ``member`` to a real role and make unrecognised roles impossible.

``member`` has existed in the database for years without existing in the code:
``choices`` is not enforced by PostgreSQL and ``Member.save()`` skips
``full_clean()``, so the value was accepted by every persistence path while
matching no role check. It was worked around by defensive comments rather than
fixed. This migration makes it a real role, sweeps up anything else that drifted
in, and adds the constraint that stops it happening again.

Order matters: the sweep must run BEFORE the constraint, or adding the
constraint fails against any row still holding an out-of-set value.
"""

from django.conf import settings
from django.db import migrations, models

from sbomify.logging import getLogger

logger = getLogger(__name__)

# Frozen deliberately, NOT read from settings.TEAMS_SUPPORTED_ROLES. A historical
# migration must describe the world as it was at this point in history: if a
# later release adds a role, a settings-derived predicate would silently change
# what this sweep spares while the AddConstraint below keeps the old list, and a
# replay from zero would fail on rows it previously migrated cleanly.
SUPPORTED_ROLES = ["owner", "admin", "member", "guest", "bot"]
INVITABLE_ROLES = ["owner", "admin", "member", "guest"]


def normalise_unrecognised_roles(apps, schema_editor):
    """Move any role outside the supported set down to ``guest``.

    Deliberately DOWN, not to ``member``: an unrecognised value carries no
    reliable intent, and guessing upwards would silently hand someone
    capabilities nobody granted them. ``member`` itself needs no update — it is
    canonical as of this migration, which is the whole point.

    Every affected row is logged, because a role change nobody asked for should
    be discoverable after the fact rather than inferred from behaviour.
    """
    Member = apps.get_model("teams", "Member")
    Invitation = apps.get_model("teams", "Invitation")

    # Report the promotions. Rows that already held role="member" are NOT
    # changed — making that value real is the point of this migration — but
    # yesterday they matched no role check at all, and today they carry
    # READ_INTERNAL, MANAGE and PUBLISH. That is a capability grant to accounts
    # nobody re-authorized, so it must leave a trace rather than being inferred
    # later from behaviour. Review this list and demote anyone who should not
    # have it; there is no way for the migration to tell.
    promoted = list(Member.objects.filter(role="member").values("id", "team__key", "user__email"))
    if promoted:
        logger.warning(
            "Migration 0041: %s pre-existing role='member' row(s) become real members "
            "(internal read + create/edit + artifact upload). Review: %s",
            len(promoted),
            promoted,
        )

    stale_members = Member.objects.exclude(role__in=SUPPORTED_ROLES)
    for row in stale_members.values("id", "team__key", "user__email", "role"):
        logger.warning("Migration 0041: Member role %r -> 'guest' (%s)", row["role"], row)
    updated = stale_members.update(role="guest")
    if updated:
        logger.warning("Migration 0041: normalised %s Member row(s) to 'guest'", updated)

    stale_invites = Invitation.objects.exclude(role__in=INVITABLE_ROLES)
    for row in stale_invites.values("id", "team__key", "email", "role"):
        logger.warning("Migration 0041: Invitation role %r -> 'guest' (%s)", row["role"], row)
    updated = stale_invites.update(role="guest")
    if updated:
        logger.warning("Migration 0041: normalised %s Invitation row(s) to 'guest'", updated)


def noop_reverse(apps, schema_editor):
    """Nothing to undo: the original values are unknown and were unusable anyway."""


class Migration(migrations.Migration):
    dependencies = [
        ("teams", "0040_team_patch_sla_days"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="invitation",
            name="role",
            field=models.CharField(
                choices=[
                    ("owner", "Owner"),
                    ("admin", "Admin"),
                    ("member", "Member"),
                    ("guest", "Guest"),
                ],
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="role",
            field=models.CharField(
                choices=[
                    ("owner", "Owner"),
                    ("admin", "Admin"),
                    ("member", "Member"),
                    ("guest", "Guest"),
                    ("bot", "Bot"),
                ],
                max_length=255,
            ),
        ),
        migrations.RunPython(normalise_unrecognised_roles, noop_reverse),
        migrations.AddConstraint(
            model_name="member",
            constraint=models.CheckConstraint(
                condition=models.Q(("role__in", ["owner", "admin", "member", "guest", "bot"])),
                name="member_role_is_supported",
            ),
        ),
    ]

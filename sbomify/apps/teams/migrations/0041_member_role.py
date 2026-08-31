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
    promoted = Member.objects.filter(role="member")
    promoted_count = promoted.count()
    if promoted_count:
        # Membership IDs, not emails, and a bounded sample. Deploy logs are
        # widely readable and long-lived, so putting every affected user's email
        # in one there trades a privacy problem for an operational convenience —
        # and on a large install the entry would be unusable anyway. The IDs are
        # enough to pull the rows back out.
        sample = list(promoted.values_list("id", flat=True)[:20])
        logger.warning(
            "Migration 0041: %s pre-existing role='member' row(s) become real members "
            "(internal read + create/edit + artifact upload). Review these Member ids "
            "and demote any that should not have it — the migration cannot tell. "
            "First %s: %s",
            promoted_count,
            len(sample),
            sample,
        )

    stale_members = Member.objects.exclude(role__in=SUPPORTED_ROLES)
    stale_sample = list(stale_members.values_list("id", flat=True)[:20])
    stale_roles = sorted(set(stale_members.values_list("role", flat=True)[:100]))
    updated = stale_members.update(role="guest")
    if updated:
        # Count, the distinct values seen and a bounded id sample — not a line
        # per row. One log line per member would be unbounded on a large install
        # and adds nothing the ids do not.
        logger.warning(
            "Migration 0041: normalised %s Member row(s) with unrecognised roles %s to 'guest'. First %s ids: %s",
            updated,
            stale_roles,
            len(stale_sample),
            stale_sample,
        )

    stale_invites = Invitation.objects.exclude(role__in=INVITABLE_ROLES)
    invite_sample = list(stale_invites.values_list("id", flat=True)[:20])
    invite_roles = sorted(set(stale_invites.values_list("role", flat=True)[:100]))
    updated = stale_invites.update(role="guest")
    if updated:
        logger.warning(
            "Migration 0041: normalised %s Invitation row(s) with unrecognised roles %s to 'guest'. First %s ids: %s",
            updated,
            invite_roles,
            len(invite_sample),
            invite_sample,
        )


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
        # Invitation was only constrained against "bot", so every other
        # unrecognised value stayed insertable — and an invitation is a deferred
        # Member row, so it sat there until accept time and then failed against
        # the constraint above. Replaced with the invitable set, which subsumes
        # the bot rule.
        migrations.RemoveConstraint(
            model_name="invitation",
            name="invitation_role_not_bot",
        ),
        migrations.AddConstraint(
            model_name="invitation",
            constraint=models.CheckConstraint(
                condition=models.Q(("role__in", ["owner", "admin", "member", "guest"])),
                name="invitation_role_is_invitable",
            ),
        ),
    ]

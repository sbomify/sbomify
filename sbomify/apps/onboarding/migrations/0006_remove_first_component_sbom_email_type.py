"""Drop the legacy ``first_component_sbom`` email type.

The ``first_component_sbom`` adaptive email overlapped with the new 4-stage
drip (``first_component`` day-3 + ``first_sbom`` day-7) and produced
duplicate sends — users on day 7 with a component but no SBOM were getting
both ``"Time to Upload Your First SBOM!"`` (legacy) and
``"Time to upload your first SBOM"`` (new) on the same minute.

This migration:

  1. Re-types any historical ``first_component_sbom`` rows to the matching
     new sequence type by inspecting the stored ``subject``:

       - ``"Ready to Create Your First Component? - sbomify"`` → ``first_component``
       - ``"Time to Upload Your First SBOM! - sbomify"``       → ``first_sbom``

     This preserves the per-stage sent-status so the new sequence's dedup
     catches the legacy send for the right stage, and does NOT prematurely
     suppress the *other* stage. (If we instead lumped all legacy rows into
     ``first_sbom``, a user who only got the component-focused variant
     would (a) have their real ``FIRST_SBOM`` blocked by the rewritten row
     and (b) still receive the new ``FIRST_COMPONENT``, producing a fresh
     near-duplicate.)
  2. Drops the enum value from ``email_type`` choices.

The forwards data migration is idempotent (no-op if no legacy rows exist).
Subquery filtering keeps memory bounded on large tenants and avoids any
IN-list parameter limit. The reverse is intentionally a no-op for the
data step: re-creating ``first_component_sbom`` rows from the merged ones
is ambiguous (we cannot tell merged rows from native ones).
"""

from __future__ import annotations

from typing import Any

from django.db import migrations, models

# Subject prefixes the legacy adaptive email used. The legacy code at
# sbomify/apps/onboarding/services/__init__.py:132-135 (pre-removal) chose
# between these two based on whether the user had created a component.
_LEGACY_SUBJECT_FOR_FIRST_COMPONENT = "Ready to Create Your First Component?"
_LEGACY_SUBJECT_FOR_FIRST_SBOM = "Time to Upload Your First SBOM!"


def merge_legacy_first_component_sbom_rows(apps: Any, schema_editor: Any) -> None:
    OnboardingEmail = apps.get_model("onboarding", "OnboardingEmail")

    legacy_rows = OnboardingEmail.objects.filter(email_type="first_component_sbom")
    if not legacy_rows.exists():
        return

    _retype_legacy_rows(
        legacy_qs=legacy_rows.filter(subject__startswith=_LEGACY_SUBJECT_FOR_FIRST_COMPONENT),
        target_type="first_component",
        OnboardingEmail=OnboardingEmail,
    )
    _retype_legacy_rows(
        legacy_qs=legacy_rows.filter(subject__startswith=_LEGACY_SUBJECT_FOR_FIRST_SBOM),
        target_type="first_sbom",
        OnboardingEmail=OnboardingEmail,
    )

    # Defensive: anything left with email_type=first_component_sbom (subject
    # didn't match either prefix — should not happen, but guard against
    # historical anomalies) is mapped to first_sbom, which is the day-7
    # stage closest to the legacy email's last semantic. Django's `choices`
    # aren't enforced at the database level, so leftover rows wouldn't
    # cause an integrity error after AlterField — but application code
    # would no longer recognize the deprecated value (no enum member, no
    # template). Cleaning them up now keeps the table consistent with the
    # post-migration model.
    leftover = OnboardingEmail.objects.filter(email_type="first_component_sbom")
    if leftover.exists():
        _retype_legacy_rows(
            legacy_qs=leftover,
            target_type="first_sbom",
            OnboardingEmail=OnboardingEmail,
        )


def _retype_legacy_rows(*, legacy_qs: Any, target_type: str, OnboardingEmail: Any) -> None:
    """Rewrite ``legacy_qs`` rows to ``target_type``, merging status on conflict.

    Three cases:

      1. **No conflict** (user has only the legacy row): update ``email_type``
         in-place. Status, ``sent_at``, ``subject``, and ``error_message`` all
         carry over unchanged.
      2. **Conflict, legacy was SENT, target is not SENT** (user has both rows
         but the legacy row is the only proof of delivery): promote the
         target row to ``SENT`` and copy ``sent_at`` from the legacy row,
         then delete the legacy row. Without this, the new sequence would
         see the target row at PENDING/FAILED and resend the email even
         though it was already delivered under the legacy type.
      3. **Conflict, target is already SENT (or both rows are pre-send)**:
         the target row is authoritative; just delete the legacy row.

    Uses Subqueries against ``OnboardingEmail`` filtered by ``target_type``
    rather than materialising user IDs in Python — keeps memory bounded and
    sidesteps any DB driver IN-list parameter limit.
    """
    users_with_target = OnboardingEmail.objects.filter(email_type=target_type).values("user_id")

    # Case 1: legacy rows for users without a target row → re-type in place.
    legacy_qs.exclude(user_id__in=users_with_target).update(email_type=target_type)

    # Case 2: promote target rows that are still PENDING/FAILED to SENT when
    # the legacy row already proved delivery. Iterating per row is acceptable
    # here because the only candidates are the (small) intersection of
    # legacy-SENT × target-not-SENT for the same user. We carry over both
    # ``status`` and ``sent_at`` so the new sequence sees the same
    # historical send timestamp.
    legacy_sent_with_target = legacy_qs.filter(
        status="sent",
        user_id__in=users_with_target,
    ).values("user_id", "sent_at")
    for row in legacy_sent_with_target:
        OnboardingEmail.objects.filter(
            email_type=target_type,
            user_id=row["user_id"],
        ).exclude(status="sent").update(
            status="sent",
            sent_at=row["sent_at"],
        )

    # Case 3 (and remainder of case 2): drop the now-redundant legacy rows.
    legacy_qs.filter(user_id__in=users_with_target).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0005_onboardingstatus_drip_started_at"),
    ]

    operations = [
        migrations.RunPython(merge_legacy_first_component_sbom_rows, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="onboardingemail",
            name="email_type",
            field=models.CharField(
                choices=[
                    ("welcome", "Welcome"),
                    ("quick_start", "Quick Start Guide"),
                    ("first_component", "First Component"),
                    ("first_sbom", "First SBOM"),
                    ("collaboration", "Team Collaboration"),
                ],
                max_length=50,
            ),
        ),
    ]

"""Drop the legacy ``first_component_sbom`` email type.

The ``first_component_sbom`` adaptive email overlapped with the new 4-stage
drip (``first_component`` day-3 + ``first_sbom`` day-7) and produced
duplicate sends — users on day 7 with a component but no SBOM were getting
both ``"Time to Upload Your First SBOM!"`` (legacy) and
``"Time to upload your first SBOM"`` (new) on the same minute.

This migration:

  1. Rewrites any historical ``first_component_sbom`` rows to ``first_sbom``
     so their sent-status is preserved and the new ``FIRST_SBOM`` path's
     dedup catches them — preventing affected users from receiving the
     ``first_sbom`` email a third time after deploy.
  2. Drops the enum value from ``email_type`` choices.

The forwards data migration is idempotent (no-op if no legacy rows exist).
The reverse is intentionally not provided for the data step: re-creating
``first_component_sbom`` rows from the merged ``first_sbom`` rows is
ambiguous (we cannot tell merged from native).
"""

from __future__ import annotations

from typing import Any

from django.db import migrations, models


def merge_legacy_first_component_sbom_rows(apps: Any, schema_editor: Any) -> None:
    OnboardingEmail = apps.get_model("onboarding", "OnboardingEmail")

    legacy_rows = OnboardingEmail.objects.filter(email_type="first_component_sbom")
    if not legacy_rows.exists():
        return

    # If a user already has a `first_sbom` row, drop the legacy one — the new
    # row is authoritative. Otherwise rewrite the legacy row's email_type so
    # the (user, email_type) pair represents the SBOM step in the new model.
    # Use a subquery rather than materialising the user_id set in Python — keeps
    # memory bounded on large tenants and avoids the IN (?, ?, ...) parameter
    # limit some DB drivers enforce on long ID lists.
    users_with_first_sbom = OnboardingEmail.objects.filter(email_type="first_sbom").values("user_id")

    legacy_rows.filter(user_id__in=users_with_first_sbom).delete()
    legacy_rows.exclude(user_id__in=users_with_first_sbom).update(email_type="first_sbom")


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

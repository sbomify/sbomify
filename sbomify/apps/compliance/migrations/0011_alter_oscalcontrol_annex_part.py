"""Advertise the allowed ``annex_part`` values via ``TextChoices``.

The previous free-form ``CharField(max_length=10)`` silently accepted
any string. Adding ``choices=AnnexPart.choices`` surfaces the legal
values in admin dropdowns, form ``clean()``, and serializer schemas,
but — important — ``choices`` is NOT enforced on ``Model.save()`` or
``bulk_create()``. Write-path enforcement is handled by:

  * ``import_catalog_to_db`` validating ``annex_part`` against the
    allowed set and raising ``ValueError`` on unknown input, and
  * Migration 0012's tightened ``CheckConstraint`` that enumerates
    the two legal ``(annex_part, is_mandatory)`` pairs explicitly.

This migration is purely cosmetic for existing data (every row is
already ``part-i`` or ``part-ii`` from 0007's backfill); the real
guarantee lives in 0012 + the import validator.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("compliance", "0010_oscalcontrol_is_mandatory_iff_part_ii"),
    ]

    operations = [
        migrations.AlterField(
            model_name="oscalcontrol",
            name="annex_part",
            field=models.CharField(
                choices=[
                    ("part-i", "Part I (Essential requirements)"),
                    ("part-ii", "Part II (Vulnerability handling)"),
                ],
                default="part-i",
                help_text="Which part of CRA Annex I this control belongs to (part-i or part-ii)",
                max_length=10,
            ),
        ),
    ]

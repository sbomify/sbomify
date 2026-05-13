"""Tighten the ``is_mandatory`` biconditional to enumerate legal pairs.

The 0010 constraint used ``(part-ii ∧ mandatory) ∨ (¬part-ii ∧
¬mandatory)``, which accepts any non-``part-ii`` string with
``is_mandatory=False`` — including typos like ``part-iii`` that would
silently downgrade a vulnerability-handling control. Rewrite the
constraint to enumerate the two canonical pairs explicitly so a
catalog import whose JSON drifts (or a hand-edit that fat-fingers the
enum) fails closed at the DB layer rather than weakening the Part II
gate.

``AddConstraint`` / ``RemoveConstraint`` pair is reversible: rolling
back past 0012 restores the looser 0010 constraint.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("compliance", "0011_alter_oscalcontrol_annex_part"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="oscalcontrol",
            name="oscal_control_is_mandatory_iff_part_ii",
        ),
        migrations.AddConstraint(
            model_name="oscalcontrol",
            constraint=models.CheckConstraint(
                check=(
                    (models.Q(annex_part="part-ii") & models.Q(is_mandatory=True))
                    | (models.Q(annex_part="part-i") & models.Q(is_mandatory=False))
                ),
                name="oscal_control_is_mandatory_iff_part_ii",
            ),
        ),
    ]

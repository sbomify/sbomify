"""Add DB-level CheckConstraint enforcing ``is_mandatory`` biconditional.

Until this constraint, the invariant ``is_mandatory == (annex_part ==
"part-ii")`` was enforced only by convention across four code paths
(schema import, migration 0007 backfill, ``update_finding`` gate, and
the Alpine badge). Any future edit that slipped the equivalence
through any one of those paths would silently desynchronise rows and
let a Part II control be marked N/A.

Anchoring the invariant at the DB makes the equivalence a first-class
property of the data, not a convention the app can break.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("compliance", "0009_remap_legacy_critical_eucc"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="oscalcontrol",
            constraint=models.CheckConstraint(
                check=(
                    (models.Q(annex_part="part-ii") & models.Q(is_mandatory=True))
                    | (~models.Q(annex_part="part-ii") & models.Q(is_mandatory=False))
                ),
                name="oscal_control_is_mandatory_iff_part_ii",
            ),
        ),
    ]

"""Drop ``BillingPlan.max_projects``.

The Project layer was removed in #946. The ``max_projects`` quota has no
real meaning under the direct ``Product → Component`` model, so we drop
the column outright (per the maintainer's default suggestion in PR #946).

Any team-level ``billing_plan_limits`` JSON snapshots that still contain a
``max_projects`` key are left untouched — they're historical and ignored
by post-migration code paths. No application code reads ``max_projects``
once this migration lands.
"""

from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0010_alter_billingplan_options_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="billingplan",
            name="max_projects",
        ),
    ]

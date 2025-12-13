"""
Data migration to set has_selected_plan=True for all existing teams.

Existing teams already have a billing plan (either from auto-trial or manual selection),
so we mark them as having selected a plan to prevent redirect loops.
"""

from django.db import migrations


def set_has_selected_plan_for_existing_teams(apps, schema_editor):
    """Set has_selected_plan=True for all existing teams."""
    Team = apps.get_model("teams", "Team")
    # Update all existing teams to have has_selected_plan=True
    # These teams were created before plan selection was required
    Team.objects.filter(has_selected_plan=False).update(has_selected_plan=True)


def reverse_migration(apps, schema_editor):
    """Reverse: set has_selected_plan=False for all teams."""
    Team = apps.get_model("teams", "Team")
    Team.objects.all().update(has_selected_plan=False)


class Migration(migrations.Migration):
    dependencies = [
        ("teams", "0019_add_has_selected_plan"),
    ]

    operations = [
        migrations.RunPython(
            set_has_selected_plan_for_existing_teams,
            reverse_code=reverse_migration,
        ),
    ]


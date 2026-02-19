from django.db import migrations, models


def set_existing_teams_plan_selected(apps, schema_editor):
    """Mark all existing teams as having selected a billing plan."""
    Team = apps.get_model("teams", "Team")
    Team.objects.all().update(has_selected_billing_plan=True)


class Migration(migrations.Migration):

    dependencies = [
        ("teams", "0028_team_onboarding_goal"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="has_selected_billing_plan",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            set_existing_teams_plan_selected,
            migrations.RunPython.noop,
        ),
    ]

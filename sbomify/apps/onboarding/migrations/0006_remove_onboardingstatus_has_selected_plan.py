from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0005_onboardingstatus_has_selected_plan"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="onboardingstatus",
            name="onboarding__has_sel_b6e62e_idx",
        ),
        migrations.RemoveField(
            model_name="onboardingstatus",
            name="has_selected_plan",
        ),
        migrations.RemoveField(
            model_name="onboardingstatus",
            name="plan_selected_at",
        ),
    ]

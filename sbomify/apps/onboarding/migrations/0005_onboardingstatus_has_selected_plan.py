from django.db import migrations, models


def set_existing_users_plan_selected(apps, schema_editor):
    """Mark all existing users as having selected a plan so they skip plan selection."""
    OnboardingStatus = apps.get_model("onboarding", "OnboardingStatus")
    OnboardingStatus.objects.all().update(has_selected_plan=True)


def reverse_plan_selected(apps, schema_editor):
    """Reverse: set all to False."""
    OnboardingStatus = apps.get_model("onboarding", "OnboardingStatus")
    OnboardingStatus.objects.all().update(has_selected_plan=False)


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0004_alter_onboardingemail_email_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="onboardingstatus",
            name="has_selected_plan",
            field=models.BooleanField(
                default=False,
                help_text="Whether the user has selected a billing plan during onboarding",
            ),
        ),
        migrations.AddField(
            model_name="onboardingstatus",
            name="plan_selected_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the user selected their billing plan",
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name="onboardingstatus",
            index=models.Index(
                fields=["has_selected_plan"],
                name="onboarding__has_sel_b6e62e_idx",
            ),
        ),
        # Data migration: mark all existing users as having selected a plan
        migrations.RunPython(
            set_existing_users_plan_selected,
            reverse_plan_selected,
        ),
    ]

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("teams", "0049_rename_team_permissions"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="advisory_id_prefix",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Prefix for new security advisory ids, e.g. ACME-SA. Blank uses one derived from the name.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="advisory_id_start_at",
            field=models.PositiveIntegerField(
                default=1,
                help_text="Lowest number a new security advisory id may take in each year's sequence.",
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(999999),
                ],
            ),
        ),
    ]

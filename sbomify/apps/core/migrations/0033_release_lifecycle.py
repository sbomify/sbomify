from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0032_drop_document_revision_vex_pins"),
    ]

    operations = [
        migrations.AddField(
            model_name="release",
            name="archived_at",
            field=models.DateTimeField(blank=True, help_text="When the release was archived", null=True),
        ),
        migrations.AddField(
            model_name="release",
            name="end_of_life",
            field=models.DateField(blank=True, help_text="End of life, derived from CLE events", null=True),
        ),
        migrations.AddField(
            model_name="release",
            name="end_of_support",
            field=models.DateField(
                blank=True,
                help_text="Final end of support across support policies, derived from CLE events",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="release",
            name="superseded_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the earliest drop-in successor took over, derived from CLE events",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="release",
            name="withdrawn_at",
            field=models.DateTimeField(blank=True, help_text="When the release was withdrawn", null=True),
        ),
        migrations.AddField(
            model_name="release",
            name="withdrawn_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("defective", "Defective"),
                    ("compromised", "Compromised"),
                    ("published_in_error", "Published in error"),
                ],
                default="",
                help_text="Why the release was withdrawn",
                max_length=30,
            ),
        ),
    ]

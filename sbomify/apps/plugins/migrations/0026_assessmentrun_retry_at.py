"""Keep long server-requested waits out of the stranded-run sweep."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("plugins", "0025_assessmentrun_plugins_ar_findings_key_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessmentrun",
            name="retry_at",
            field=models.DateTimeField(
                blank=True, null=True, help_text="When the next deferred assessment attempt is due"
            ),
        ),
    ]

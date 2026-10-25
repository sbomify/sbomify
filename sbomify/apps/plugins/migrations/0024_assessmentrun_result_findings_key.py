"""Add ``AssessmentRun.result_findings_key``.

A column with a constant default is metadata-only on PostgreSQL 11+, so this is
instant on a very large table, as ``result_object_key`` was in 0022.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("plugins", "0023_assessmentrun_plugins_ar_offload_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessmentrun",
            name="result_findings_key",
            field=models.CharField(
                blank=True,
                default="",
                editable=False,
                help_text="Object-storage key of the shared findings array of an offloaded result. Empty when inline.",
                max_length=255,
            ),
        ),
    ]

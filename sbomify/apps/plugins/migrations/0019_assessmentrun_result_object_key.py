"""Add ``AssessmentRun.result_object_key``.

Adding a nullable-in-practice column with a constant default is metadata-only on
PostgreSQL 11+, so this is instant on a very large table and takes no long lock.
The same property is documented beside ``result_summary``, which was added to
this table for the same reason.

The payloads themselves are moved by the ``offload_assessment_results``
management command, not here: a data migration over this table holds one long
lock and has been unrunnable at production size before.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("plugins", "0018_alter_teampluginsettings_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessmentrun",
            name="result_object_key",
            field=models.CharField(
                blank=True,
                default="",
                editable=False,
                help_text="Object-storage key holding the offloaded result payload. Empty when result is inline.",
                max_length=255,
            ),
        ),
    ]

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # CONCURRENTLY, so scans keep writing runs while it builds; it cannot run
    # inside a transaction. Every existing row has an empty key, so the partial
    # index starts empty.
    atomic = False

    dependencies = [
        ("plugins", "0024_assessmentrun_result_findings_key"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="assessmentrun",
            index=models.Index(
                condition=models.Q(("result_findings_key", ""), _negated=True),
                fields=["result_findings_key"],
                name="plugins_ar_findings_key_idx",
            ),
        ),
    ]

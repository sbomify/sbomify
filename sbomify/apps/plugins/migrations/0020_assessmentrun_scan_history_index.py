from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction. Building it
    # concurrently keeps scans writing to this table while the index builds.
    atomic = False

    dependencies = [
        ("plugins", "0019_drop_cra_compliance_from_team_settings"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="assessmentrun",
            index=models.Index(
                condition=models.Q(("category", "security"), ("status", "completed")),
                fields=["sbom", "created_at"],
                name="plugins_scan_history_idx",
            ),
        ),
    ]

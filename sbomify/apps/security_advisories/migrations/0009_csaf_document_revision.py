# Per-document CSAF revision: the workspace marker says the distribution moved,
# this says which document did. See security_advisories/signals.py.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("security_advisories", "0008_advisoryproduct_public_name_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="securityadvisory",
            name="csaf_revision",
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
        migrations.AddField(
            model_name="securityadvisory",
            name="csaf_revision_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]

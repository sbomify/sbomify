from django.db import migrations, models


def mark_existing_names_public(apps, schema_editor):
    """Existing NULL-product rows are external names, not deleted products.

    Before this column the projection treated every NULL ``product`` as a name
    the workspace typed in and printed it. Defaulting them to False would
    retroactively withhold names that are already published, so the old
    behaviour is carried forward for the rows that predate the flag.
    """
    AdvisoryProduct = apps.get_model("security_advisories", "AdvisoryProduct")
    AdvisoryProduct.objects.using(schema_editor.connection.alias).filter(product__isnull=True).update(
        public_name_snapshot=True
    )


class Migration(migrations.Migration):
    dependencies = [
        ("security_advisories", "0007_initialize_csaf_markers"),
    ]

    operations = [
        migrations.AddField(
            model_name="advisoryproduct",
            name="public_name_snapshot",
            field=models.BooleanField(
                default=False,
                editable=False,
                help_text="The retained name was typed in, or its product was public when it was deleted.",
            ),
        ),
        migrations.RunPython(mark_existing_names_public, migrations.RunPython.noop),
    ]

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("sboms", "0051_add_sbom_qualifiers"),
    ]

    operations = [
        migrations.DeleteModel(
            name="ComponentIdentifier",
        ),
    ]

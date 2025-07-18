# Generated by Django 5.2.3 on 2025-07-07 10:23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="document",
            name="document_type",
            field=models.CharField(
                blank=True,
                help_text="Type of document (e.g., specification, manual, report, compliance)",
                max_length=100,
            ),
        ),
    ]

# Generated manually for lifecycle event fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sboms", "0042_remove_productlink_unique_constraint"),
    ]

    operations = [
        # Add lifecycle event fields to Product
        migrations.AddField(
            model_name="product",
            name="release_date",
            field=models.DateField(
                blank=True, null=True, help_text="Release date of the product"
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="end_of_support",
            field=models.DateField(
                blank=True,
                null=True,
                help_text="Date when bugfixes stop (security-only after this)",
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="end_of_life",
            field=models.DateField(
                blank=True, null=True, help_text="Date when all support ends"
            ),
        ),
        # Add lifecycle event fields to Component
        migrations.AddField(
            model_name="component",
            name="release_date",
            field=models.DateField(
                blank=True, null=True, help_text="Release date of the component"
            ),
        ),
        migrations.AddField(
            model_name="component",
            name="end_of_support",
            field=models.DateField(
                blank=True,
                null=True,
                help_text="Date when bugfixes stop (security-only after this)",
            ),
        ),
        migrations.AddField(
            model_name="component",
            name="end_of_life",
            field=models.DateField(
                blank=True, null=True, help_text="Date when all support ends"
            ),
        ),
    ]

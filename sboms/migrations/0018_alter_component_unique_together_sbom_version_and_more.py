# Generated by Django 5.0.4 on 2024-08-02 06:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sboms", "0018_1_remove_duplicate_components"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="component",
            unique_together={("team", "name")},
        ),
        migrations.AddField(
            model_name="sbom",
            name="version",
            field=models.CharField(default="", max_length=255),
        ),
        migrations.RemoveField(
            model_name="component",
            name="version",
        ),
    ]

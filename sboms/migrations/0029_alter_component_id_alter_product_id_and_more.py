# Generated by Django 5.1.4 on 2025-01-09 13:23

import core.utils
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sboms", "0028_merge_20241129_1747"),
    ]

    operations = [
        migrations.AlterField(
            model_name="component",
            name="id",
            field=models.CharField(
                default=core.utils.generate_id,
                max_length=20,
                primary_key=True,
                serialize=False,
            ),
        ),
        migrations.AlterField(
            model_name="product",
            name="id",
            field=models.CharField(
                default=core.utils.generate_id,
                max_length=20,
                primary_key=True,
                serialize=False,
            ),
        ),
        migrations.AlterField(
            model_name="productproject",
            name="id",
            field=models.CharField(
                default=core.utils.generate_id,
                max_length=20,
                primary_key=True,
                serialize=False,
            ),
        ),
        migrations.AlterField(
            model_name="project",
            name="id",
            field=models.CharField(
                default=core.utils.generate_id,
                max_length=20,
                primary_key=True,
                serialize=False,
            ),
        ),
        migrations.AlterField(
            model_name="projectcomponent",
            name="id",
            field=models.CharField(
                default=core.utils.generate_id,
                max_length=20,
                primary_key=True,
                serialize=False,
            ),
        ),
        migrations.AlterField(
            model_name="sbom",
            name="id",
            field=models.CharField(
                default=core.utils.generate_id,
                max_length=20,
                primary_key=True,
                serialize=False,
            ),
        ),
    ]

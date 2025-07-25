# Generated by Django 5.2.3 on 2025-07-02 08:51

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_backfill_user_names_from_socialaccount"),
        ("sboms", "0030_remove_sbom_licenses_remove_sbom_packages_licenses"),
    ]

    operations = [
        migrations.CreateModel(
            name="Component",
            fields=[],
            options={
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("sboms.component",),
        ),
        migrations.CreateModel(
            name="Product",
            fields=[],
            options={
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("sboms.product",),
        ),
        migrations.CreateModel(
            name="ProductProject",
            fields=[],
            options={
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("sboms.productproject",),
        ),
        migrations.CreateModel(
            name="Project",
            fields=[],
            options={
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("sboms.project",),
        ),
        migrations.CreateModel(
            name="ProjectComponent",
            fields=[],
            options={
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("sboms.projectcomponent",),
        ),
    ]

# Generated by Django 5.2.3 on 2025-07-18 10:10

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0002_alter_document_document_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="document",
            name="document_type",
            field=models.CharField(
                choices=[
                    ("specification", "Specification"),
                    ("manual", "Manual"),
                    ("readme", "README"),
                    ("documentation", "Documentation"),
                    ("build-instructions", "Build Instructions"),
                    ("configuration", "Configuration"),
                    ("license", "License"),
                    ("compliance", "Compliance"),
                    ("evidence", "Evidence"),
                    ("changelog", "Changelog"),
                    ("release-notes", "Release Notes"),
                    ("security-advisory", "Security Advisory"),
                    ("vulnerability-report", "Vulnerability Report"),
                    ("threat-model", "Threat Model"),
                    ("risk-assessment", "Risk Assessment"),
                    ("pentest-report", "Penetration Test Report"),
                    ("static-analysis", "Static Analysis Report"),
                    ("dynamic-analysis", "Dynamic Analysis Report"),
                    ("quality-metrics", "Quality Metrics"),
                    ("maturity-report", "Maturity Report"),
                    ("report", "Report"),
                    ("other", "Other"),
                ],
                default="other",
                help_text="Type of document aligned with SPDX and CycloneDX standards",
                max_length=50,
            ),
        ),
    ]

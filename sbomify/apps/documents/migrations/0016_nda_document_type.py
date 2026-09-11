"""An NDA is its own document type, not a compliance subcategory.

A compliance document is an attestation about the workspace; an NDA is an
agreement the reader signs before they are shown one. Filing it under
``COMPLIANCE`` made ``ComplianceSubcategory`` mean two different kinds of thing
and forced every consumer to carve the NDA back out again.

Unlike 0015 this reverses cleanly: after the forward pass a row with
``document_type='nda'`` is exactly a row this migration moved, so the inverse
puts back what it took.
"""

from django.db import migrations, models

COMPLIANCE = "compliance"
NDA = "nda"


def move_nda_out_of_compliance(apps, schema_editor):
    Document = apps.get_model("documents", "Document")
    Document.objects.filter(document_type=COMPLIANCE, compliance_subcategory=NDA).update(
        document_type=NDA, compliance_subcategory=None
    )


def move_nda_back_into_compliance(apps, schema_editor):
    Document = apps.get_model("documents", "Document")
    Document.objects.filter(document_type=NDA).update(document_type=COMPLIANCE, compliance_subcategory=NDA)


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0015_certification_subcategories"),
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
                    ("nda", "NDA"),
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
        migrations.RunPython(move_nda_out_of_compliance, move_nda_back_into_compliance),
        migrations.AlterField(
            model_name="document",
            name="compliance_subcategory",
            field=models.CharField(
                blank=True,
                choices=[
                    ("soc2-type1", "SOC 2 Type I"),
                    ("soc2-type2", "SOC 2 Type II"),
                    ("iso27001", "ISO 27001"),
                    ("cra", "CRA"),
                ],
                help_text="Compliance subcategory for auto-detection and badging",
                max_length=50,
                null=True,
            ),
        ),
    ]

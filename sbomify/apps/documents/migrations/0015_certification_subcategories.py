"""Certification subcategories for the trust-center badges.

Adds SOC 2 Type I / Type II and CRA, and retires the undifferentiated ``soc2``:
a SOC 2 report is one type or the other, so the plain value described no real
document. Its rows move to Type II, which is what is almost always meant.
"""

from django.db import migrations, models

# The value being retired, and where its rows land.
RETIRED_SOC2 = "soc2"
SOC2_TYPE2 = "soc2-type2"


def move_plain_soc2_to_type_ii(apps, schema_editor):
    Document = apps.get_model("documents", "Document")
    Document.objects.filter(compliance_subcategory=RETIRED_SOC2).update(compliance_subcategory=SOC2_TYPE2)


def unmigrate(apps, schema_editor):
    """Deliberately a no-op rather than the inverse.

    After the forward pass a moved row and a genuine Type II report are
    indistinguishable, so sending every Type II back to plain ``soc2`` would
    mislabel reports that were correct all along. Leaving them as Type II is
    wrong for at most the rows this migration touched; reversing is wrong for
    every Type II in the table.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0014_rename_documents_a_team_id_838fe2_idx_documents_a_workspa_17946d_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(move_plain_soc2_to_type_ii, unmigrate),
        migrations.AlterField(
            model_name="document",
            name="compliance_subcategory",
            field=models.CharField(
                blank=True,
                choices=[
                    ("nda", "NDA"),
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

import logging

from django.db import migrations, models
from django.db.models import Count, Exists, OuterRef

logger = logging.getLogger(__name__)


def mark_duplicate_sboms(apps, schema_editor):
    """Assign unique qualifiers to duplicate SBOMs before adding the unique constraint.

    After adding the `qualifiers` column (default={}), rows that were previously
    unique on (component, version, format) may now collide on
    (component, version, format, qualifiers).  For each duplicate group we prefer
    to keep the SBOM referenced by a release or assessment run (otherwise the newest)
    with qualifiers={}, and mark the rest with {"duplicate": "1"}, {"duplicate": "2"}, etc.
    """
    SBOM = apps.get_model("sboms", "SBOM")
    ReleaseArtifact = apps.get_model("core", "ReleaseArtifact")
    AssessmentRun = apps.get_model("plugins", "AssessmentRun")

    dupes = list(SBOM.objects.values("component_id", "version", "format").annotate(cnt=Count("id")).filter(cnt__gt=1))

    total_marked = 0
    for group in dupes:
        siblings = SBOM.objects.filter(
            component_id=group["component_id"],
            version=group["version"],
            format=group["format"],
        )

        # Prefer: referenced by release > referenced by assessment > newest
        ranked = list(
            siblings.annotate(
                has_release=Exists(ReleaseArtifact.objects.filter(sbom=OuterRef("pk"))),
                has_assessment=Exists(AssessmentRun.objects.filter(sbom=OuterRef("pk"))),
            )
            .order_by("-has_release", "-has_assessment", "-created_at")
            .values_list("id", flat=True)
        )

        # First one keeps qualifiers={}, rest get {"duplicate": "N"}
        for seq, sbom_id in enumerate(ranked[1:], start=1):
            SBOM.objects.filter(id=sbom_id).update(qualifiers={"duplicate": str(seq)})
            total_marked += 1

    if total_marked:
        logger.info("Marked %d duplicate SBOM row(s) before adding unique constraint", total_marked)


class Migration(migrations.Migration):
    dependencies = [
        ("sboms", "0050_component_uuid_product_uuid_sbom_uuid"),
        ("core", "0021_release_uuid"),
        ("plugins", "0007_add_is_builtin_field"),
    ]

    operations = [
        migrations.AddField(
            model_name="sbom",
            name="qualifiers",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="PURL qualifiers distinguishing build variants (e.g., arch, distro). Canonicalized on save.",
            ),
        ),
        migrations.RunPython(mark_duplicate_sboms, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="sbom",
            constraint=models.UniqueConstraint(
                fields=["component", "version", "format", "qualifiers"],
                name="sboms_sbom_unique_component_version_format_qualifiers",
            ),
        ),
    ]

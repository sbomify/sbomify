import logging

from django.db import migrations, models
from django.db.models import Count, Exists, OuterRef

logger = logging.getLogger(__name__)


def deduplicate_sboms(apps, schema_editor):
    """Remove duplicate SBOMs before adding the unique constraint.

    After adding the `qualifiers` column (default={}), rows that were previously
    unique on (component, version, format) may now collide on
    (component, version, format, qualifiers).  For each duplicate group we prefer
    to keep an SBOM referenced by a release or assessment run; otherwise the newest.
    """
    SBOM = apps.get_model("sboms", "SBOM")
    ReleaseArtifact = apps.get_model("core", "ReleaseArtifact")
    AssessmentRun = apps.get_model("plugins", "AssessmentRun")

    dupes = list(SBOM.objects.values("component_id", "version", "format").annotate(cnt=Count("id")).filter(cnt__gt=1))

    total_deleted = 0
    for group in dupes:
        siblings = SBOM.objects.filter(
            component_id=group["component_id"],
            version=group["version"],
            format=group["format"],
        )

        # Prefer: referenced by release > referenced by assessment > newest
        keep = (
            siblings.annotate(
                has_release=Exists(ReleaseArtifact.objects.filter(sbom=OuterRef("pk"))),
                has_assessment=Exists(AssessmentRun.objects.filter(sbom=OuterRef("pk"))),
            )
            .order_by("-has_release", "-has_assessment", "-created_at")
            .values_list("id", flat=True)
            .first()
        )
        if keep is None:
            continue

        deleted, _ = siblings.exclude(id=keep).delete()
        total_deleted += deleted

    if total_deleted:
        logger.info("Deduplicated %d SBOM row(s) before adding unique constraint", total_deleted)


class Migration(migrations.Migration):
    dependencies = [
        ("sboms", "0050_component_uuid_product_uuid_sbom_uuid"),
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
        migrations.RunPython(deduplicate_sboms, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="sbom",
            constraint=models.UniqueConstraint(
                fields=["component", "version", "format", "qualifiers"],
                name="sboms_sbom_unique_component_version_format_qualifiers",
            ),
        ),
    ]

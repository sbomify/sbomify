import logging

from django.db import migrations, models
from django.db.models import Count, Max

logger = logging.getLogger(__name__)


def deduplicate_sboms(apps, schema_editor):
    """Remove duplicate SBOMs before adding the unique constraint.

    After adding the `qualifiers` column (default={}), rows that were previously
    unique on (component, version, format) may now collide on
    (component, version, format, qualifiers).  For each duplicate group we keep
    the most recently created row and delete the rest.
    """
    SBOM = apps.get_model("sboms", "SBOM")

    dupes = (
        SBOM.objects.values("component_id", "version", "format")
        .annotate(cnt=Count("id"), newest=Max("created_at"))
        .filter(cnt__gt=1)
    )

    total_deleted = 0
    for group in dupes:
        # Keep the single newest row; delete the rest
        keep = (
            SBOM.objects.filter(
                component_id=group["component_id"],
                version=group["version"],
                format=group["format"],
                created_at=group["newest"],
            )
            .values_list("id", flat=True)
            .first()
        )
        if keep is None:
            continue
        deleted, _ = (
            SBOM.objects.filter(
                component_id=group["component_id"],
                version=group["version"],
                format=group["format"],
            )
            .exclude(id=keep)
            .delete()
        )
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

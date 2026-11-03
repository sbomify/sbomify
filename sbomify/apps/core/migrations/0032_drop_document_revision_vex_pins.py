"""Document revisions do not bind OpenVEX or CSAF to a component version."""

from django.db import migrations
from django.db.models import F
from django.utils import timezone


def drop_document_revision_pins(apps, schema_editor):
    ReleaseArtifact = apps.get_model("core", "ReleaseArtifact")
    Release = apps.get_model("core", "Release")
    pins = ReleaseArtifact.objects.filter(auto_pinned=True, sbom__bom_type="vex", sbom__format__in=("openvex", "csaf"))
    release_ids = set(pins.order_by().values_list("release_id", flat=True))
    if not release_ids:
        return
    pins.delete()
    Release.objects.filter(pk__in=release_ids).update(
        collection_version=F("collection_version") + 1,
        collection_updated_at=timezone.now(),
        collection_update_reason="ARTIFACT_REMOVED",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0031_drop_vex_pins_for_other_versions"),
    ]

    operations = [
        migrations.RunPython(drop_document_revision_pins, migrations.RunPython.noop),
    ]

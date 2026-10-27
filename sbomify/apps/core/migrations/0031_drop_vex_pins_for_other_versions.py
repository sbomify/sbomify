from django.db import migrations, models
from django.db.models import F
from django.utils import timezone


def _version_key(value):
    """Mirrors vulnerability_scanning.vex.vex_version_key, frozen for this migration."""
    if not isinstance(value, str):
        return None
    return value.strip().lower().lstrip("v") or None


def _drop_vex_pins_for_other_versions(apps, schema_editor):
    """Remove VEX that sbomify pinned to a release it was not written for.

    Releases used to carry their component's newest VEX whatever version it was
    for, so a statement verified against one build cleared findings in the next.
    Only auto pins go: a pin made by hand is a deliberate claim and stays. The
    VEX written for a release's version is pinned again by the next VEX change
    on the component, and applies to its scans meanwhile without a pin.
    """
    ReleaseArtifact = apps.get_model("core", "ReleaseArtifact")
    Release = apps.get_model("core", "Release")

    shipped: dict[tuple, set] = {}
    for release_id, component_id, version in ReleaseArtifact.objects.filter(sbom__bom_type="sbom").values_list(
        "release_id", "sbom__component_id", "sbom__version"
    ):
        key = _version_key(version)
        if key is not None:
            shipped.setdefault((release_id, component_id), set()).add(key)

    stale = [
        (pk, release_id)
        for pk, release_id, component_id, version in ReleaseArtifact.objects.filter(
            auto_pinned=True, sbom__bom_type="vex"
        ).values_list("pk", "release_id", "sbom__component_id", "sbom__version")
        if _version_key(version) not in shipped.get((release_id, component_id), set())
    ]
    if not stale:
        return
    ReleaseArtifact.objects.filter(pk__in=[pk for pk, _ in stale]).delete()
    # Consumers track the artifact set by its collection version, so a removal
    # they cannot see would leave them serving the dropped VEX.
    Release.objects.filter(pk__in={release_id for _, release_id in stale}).update(
        collection_version=F("collection_version") + 1,
        collection_updated_at=timezone.now(),
        collection_update_reason="ARTIFACT_REMOVED",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0030_user_email_case_insensitive_unique"),
    ]

    operations = [
        migrations.AlterField(
            model_name="releaseartifact",
            name="auto_pinned",
            field=models.BooleanField(
                default=False,
                help_text="Pinned automatically by sbomify (latest-release maintenance, or the VEX written for the version a release ships). Only auto-pinned VEX pins are ever re-pointed when a newer VEX for that version appears; a manually pinned artifact is never replaced automatically.",
            ),
        ),
        migrations.RunPython(_drop_vex_pins_for_other_versions, migrations.RunPython.noop),
    ]

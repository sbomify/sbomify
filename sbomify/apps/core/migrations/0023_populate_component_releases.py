"""Data migration: populate ComponentRelease from existing SBOMs.

Groups existing SBOMs by (component, version, qualifiers) and creates
ComponentRelease + ComponentReleaseArtifact rows with fresh uuid4s.

Non-destructive: no existing data is modified or deleted.
Reversible: reverse deletes all ComponentRelease rows (cascades to artifacts).
"""

from __future__ import annotations

import json
import uuid as uuid_lib

from django.db import migrations


def populate_component_releases(apps, schema_editor):
    """Create ComponentRelease rows for existing SBOMs."""
    SBOM = apps.get_model("sboms", "SBOM")
    ComponentRelease = apps.get_model("core", "ComponentRelease")
    ComponentReleaseArtifact = apps.get_model("core", "ComponentReleaseArtifact")

    from sbomify.apps.core.utils import generate_id

    # Group SBOMs by (component, version, qualifiers)
    seen: dict[tuple[str, str, str], object] = {}  # (component_id, version, qualifiers_key) → ComponentRelease

    for sbom in SBOM.objects.select_related("component").iterator():
        qualifiers = sbom.qualifiers or {}
        qualifiers_key = json.dumps(qualifiers, sort_keys=True)
        key = (sbom.component_id, sbom.version, qualifiers_key)

        if key not in seen:
            cr = ComponentRelease.objects.create(
                id=generate_id(),
                uuid=uuid_lib.uuid4(),
                component=sbom.component,
                version=sbom.version,
                qualifiers=qualifiers,
            )
            seen[key] = cr

        ComponentReleaseArtifact.objects.create(
            id=generate_id(),
            component_release=seen[key],
            sbom=sbom,
        )


def reverse_populate(apps, schema_editor):
    """Reverse: delete all ComponentRelease rows (cascades to artifacts)."""
    ComponentRelease = apps.get_model("core", "ComponentRelease")
    ComponentRelease.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0022_component_release"),
        ("sboms", "0051_add_sbom_qualifiers"),
    ]

    operations = [
        migrations.RunPython(populate_component_releases, reverse_populate),
    ]

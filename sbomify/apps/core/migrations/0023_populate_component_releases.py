"""Data migration: populate ComponentRelease from existing SBOMs.

Groups existing SBOMs by (component, version, qualifiers) and creates
ComponentRelease + ComponentReleaseArtifact rows with fresh uuid4s.

Non-destructive: no existing data is modified or deleted.
Reversible: reverse deletes all ComponentRelease rows (cascades to artifacts).
"""

from __future__ import annotations

import json
import string
import uuid as uuid_lib

from django.db import migrations


def _generate_id() -> str:
    """Generate a 12-char alphanumeric ID.

    Frozen copy of sbomify.apps.core.utils.generate_id to keep this
    migration self-contained per Django best practices.
    """
    CHARS = string.ascii_letters + string.digits
    while True:
        random_int = int.from_bytes(uuid_lib.uuid4().bytes[:9], "big")
        base62 = ""
        temp_int = random_int
        while temp_int:
            temp_int, remainder = divmod(temp_int, 62)
            base62 = CHARS[remainder] + base62
        base62 = base62.rjust(12, "a")
        if len(base62) > 12:
            continue
        if not base62[0].isalpha():
            base62 = string.ascii_letters[random_int % 52] + base62[1:]
        return base62


def _canonicalize_qualifiers(qualifiers: dict) -> dict:
    """Canonicalize qualifiers: lowercase keys, strip values, sort.

    Frozen copy to keep migration self-contained.
    """
    if not qualifiers or not isinstance(qualifiers, dict):
        return {}
    return dict(
        sorted((k.lower(), sv) for k, v in qualifiers.items() if v is not None and (sv := str(v).strip())),
    )


def populate_component_releases(apps, schema_editor):
    """Create ComponentRelease rows for existing SBOMs."""
    SBOM = apps.get_model("sboms", "SBOM")
    ComponentRelease = apps.get_model("core", "ComponentRelease")
    ComponentReleaseArtifact = apps.get_model("core", "ComponentReleaseArtifact")

    # Process SBOMs in deterministic order and reuse the last ComponentRelease
    # for consecutive rows with the same (component, version, qualifiers) key.
    # This avoids an unbounded dict and is O(1) memory per group.
    last_key: tuple[str, str, str] | None = None
    last_cr = None
    earliest_sbom_date = None

    for sbom in (
        SBOM.objects.select_related("component")
        .order_by("component_id", "version", "qualifiers")
        .iterator()
    ):
        qualifiers = _canonicalize_qualifiers(sbom.qualifiers)
        qualifiers_key = json.dumps(qualifiers, sort_keys=True)
        key = (sbom.component_id, sbom.version, qualifiers_key)

        if key != last_key:
            # Backfill created_at on the previous group's ComponentRelease
            if last_cr is not None and earliest_sbom_date is not None:
                ComponentRelease.objects.filter(pk=last_cr.pk).update(created_at=earliest_sbom_date)

            last_cr = ComponentRelease.objects.create(
                id=_generate_id(),
                uuid=uuid_lib.uuid4(),
                component=sbom.component,
                version=sbom.version,
                qualifiers=qualifiers,
            )
            last_key = key
            earliest_sbom_date = sbom.created_at

        # Track earliest SBOM date in this group for the ComponentRelease
        if sbom.created_at and (earliest_sbom_date is None or sbom.created_at < earliest_sbom_date):
            earliest_sbom_date = sbom.created_at

        cra = ComponentReleaseArtifact.objects.create(
            id=_generate_id(),
            component_release=last_cr,
            sbom=sbom,
        )
        # Preserve original SBOM timestamp on the artifact link
        if sbom.created_at:
            ComponentReleaseArtifact.objects.filter(pk=cra.pk).update(created_at=sbom.created_at)

    # Backfill the final group
    if last_cr is not None and earliest_sbom_date is not None:
        ComponentRelease.objects.filter(pk=last_cr.pk).update(created_at=earliest_sbom_date)


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

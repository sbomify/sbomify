"""Make a document's name and version unique within its component.

Existing rows can already violate this, so duplicates are marked before the
constraint is added: the row a release points at (otherwise the newest) keeps
its version, and every sibling gets a " (duplicate N)" suffix. Nothing is
deleted, and the stored file is untouched (ADR-004) - only the metadata that
made the rows indistinguishable changes, so an operator can see which ones to
merge or remove.

The work is done in a fixed number of queries rather than per group: a
workspace that has been creating duplicates freely is exactly the one this
migration has the most rows to rewrite, and it holds the table while it runs.
"""

import logging

from django.db import migrations, models
from django.db.models import Count

logger = logging.getLogger(__name__)

VERSION_MAX_LENGTH = 255
BATCH_SIZE = 500


def _free_version(base: str, taken: set[str], seq: int) -> tuple[str, int]:
    """Next " (duplicate N)" variant of ``base`` that no sibling holds yet."""
    while True:
        suffix = f" (duplicate {seq})"
        candidate = base[: VERSION_MAX_LENGTH - len(suffix)] + suffix
        seq += 1
        if candidate not in taken:
            return candidate, seq


def mark_duplicate_documents(apps, schema_editor):
    """Give duplicate documents a distinct version before adding the constraint."""
    Document = apps.get_model("documents", "Document")
    ReleaseArtifact = apps.get_model("core", "ReleaseArtifact")

    duplicate_groups = {
        (group["component_id"], group["name"], group["version"])
        for group in Document.objects.values("component_id", "name", "version")
        .annotate(cnt=Count("id"))
        .filter(cnt__gt=1)
    }
    if not duplicate_groups:
        return

    component_ids = {component_id for component_id, _, _ in duplicate_groups}
    names = {name for _, name, _ in duplicate_groups}

    # A superset of the rows involved (every name/component pairing, not just the
    # ones that actually collide), narrowed in Python. One query either way, and
    # the siblings are needed anyway to know which suffixes are already in use.
    rows = list(
        Document.objects.filter(component_id__in=component_ids, name__in=names).only(
            "id", "component_id", "name", "version", "created_at"
        )
    )

    pinned_ids = set(
        ReleaseArtifact.objects.filter(document__component_id__in=component_ids).values_list("document_id", flat=True)
    )

    siblings_by_name: dict[tuple[str, str], list] = {}
    for row in rows:
        siblings_by_name.setdefault((row.component_id, row.name), []).append(row)

    changed = []
    for (component_id, name), siblings in siblings_by_name.items():
        taken = {row.version for row in siblings}

        by_version: dict[str, list] = {}
        for row in siblings:
            by_version.setdefault(row.version, []).append(row)

        for version, group in by_version.items():
            if (component_id, name, version) not in duplicate_groups:
                continue

            # Prefer: referenced by a release > newest
            ranked = sorted(group, key=lambda row: (row.id in pinned_ids, row.created_at), reverse=True)

            # The first row keeps the original version, the rest are suffixed.
            seq = 1
            for row in ranked[1:]:
                row.version, seq = _free_version(version, taken, seq)
                taken.add(row.version)
                changed.append(row)

    if changed:
        Document.objects.bulk_update(changed, ["version"], batch_size=BATCH_SIZE)
        logger.info("Marked %d duplicate document row(s) before adding unique constraint", len(changed))


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0014_rename_documents_a_team_id_838fe2_idx_documents_a_workspa_17946d_idx_and_more"),
        ("core", "0010_add_release_models_with_prerelease"),
    ]

    operations = [
        migrations.RunPython(mark_duplicate_documents, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="document",
            constraint=models.UniqueConstraint(
                fields=["component", "name", "version"],
                name="documents_document_unique_component_name_version",
            ),
        ),
    ]

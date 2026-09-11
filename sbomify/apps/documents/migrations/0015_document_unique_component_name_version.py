"""Make a document's name and version unique within its component.

Existing rows can already violate this, so duplicates are marked before the
constraint is added: the row a release points at (otherwise the newest) keeps
its version, and every sibling gets a " (duplicate N)" suffix. Nothing is
deleted, and the stored file is untouched (ADR-004) — only the metadata that
made the rows indistinguishable changes, so an operator can see which ones to
merge or remove.
"""

import logging

from django.db import migrations, models
from django.db.models import Count, Exists, OuterRef

logger = logging.getLogger(__name__)

VERSION_MAX_LENGTH = 255


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

    groups = list(
        Document.objects.values("component_id", "name", "version").annotate(cnt=Count("id")).filter(cnt__gt=1)
    )

    total_marked = 0
    for group in groups:
        siblings = Document.objects.filter(
            component_id=group["component_id"],
            name=group["name"],
            version=group["version"],
        )

        # Prefer: referenced by a release > newest
        ranked = list(
            siblings.annotate(has_release=Exists(ReleaseArtifact.objects.filter(document=OuterRef("pk"))))
            .order_by("-has_release", "-created_at")
            .values_list("id", flat=True)
        )

        taken = set(
            Document.objects.filter(component_id=group["component_id"], name=group["name"]).values_list(
                "version", flat=True
            )
        )

        # The first row keeps the original version, the rest are suffixed.
        seq = 1
        for document_id in ranked[1:]:
            new_version, seq = _free_version(group["version"], taken, seq)
            taken.add(new_version)
            Document.objects.filter(id=document_id).update(version=new_version)
            total_marked += 1

    if total_marked:
        logger.info("Marked %d duplicate document row(s) before adding unique constraint", total_marked)


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

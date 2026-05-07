"""Backfill ``ProductComponent`` from the existing ``Product → Project → Component`` chain.

For every (product, component) pair reachable through ``ProductProject ⨝ ProjectComponent``,
insert a ``ProductComponent`` row. ``unique_together("product", "component")`` plus
``bulk_create(..., ignore_conflicts=True)`` provide the dedup mechanism — duplicate
inserts (same component reachable through multiple projects under the same product) are
silently dropped at the DB level, so the migration code does not need to track seen pairs.

Reverse is intentionally a no-op: the legacy join tables still exist after this migration,
so the data is recoverable until ``0061_drop_project_links`` runs.
"""

from __future__ import annotations

from typing import Any

from django.db import migrations


def forwards(apps: Any, schema_editor: Any) -> None:
    ProductComponent = apps.get_model("sboms", "ProductComponent")
    ProductProject = apps.get_model("sboms", "ProductProject")
    ProjectComponent = apps.get_model("sboms", "ProjectComponent")

    pp_by_project: dict[str, list[str]] = {}
    for prod_id, proj_id in ProductProject.objects.values_list("product_id", "project_id").iterator(chunk_size=2000):
        pp_by_project.setdefault(proj_id, []).append(prod_id)

    batch: list[Any] = []
    for proj_id, comp_id in ProjectComponent.objects.values_list("project_id", "component_id").iterator(
        chunk_size=2000
    ):
        for prod_id in pp_by_project.get(proj_id, ()):
            batch.append(ProductComponent(product_id=prod_id, component_id=comp_id))
            if len(batch) >= 1000:
                ProductComponent.objects.bulk_create(batch, ignore_conflicts=True)
                batch.clear()
    if batch:
        ProductComponent.objects.bulk_create(batch, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("sboms", "0059_add_productcomponent"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

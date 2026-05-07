"""Backfill ``ProductComponent`` from the existing ``Product → Project → Component`` chain.

For every (product, component) pair reachable through ``ProductProject ⨝ ProjectComponent``,
insert a ``ProductComponent`` row, deduplicating across multiple projects that link the
same component to the same product. ``unique_together("product", "component")`` plus
``ignore_conflicts=True`` provide the dedup mechanism — no extra logic required.

Reverse is intentionally a no-op: the legacy join tables still exist after this
migration, so the data is recoverable until ``0061_drop_project_links`` runs.
"""

from __future__ import annotations

from typing import Any

from django.db import migrations


def forwards(apps: Any, schema_editor: Any) -> None:
    ProductComponent = apps.get_model("sboms", "ProductComponent")
    ProductProject = apps.get_model("sboms", "ProductProject")
    ProjectComponent = apps.get_model("sboms", "ProjectComponent")
    from sbomify.apps.core.utils import generate_id

    pp_by_project: dict[str, list[str]] = {}
    for prod_id, proj_id in ProductProject.objects.values_list(
        "product_id", "project_id"
    ).iterator(chunk_size=2000):
        pp_by_project.setdefault(proj_id, []).append(prod_id)

    seen: set[tuple[str, str]] = set()
    batch: list[Any] = []
    for proj_id, comp_id in ProjectComponent.objects.values_list(
        "project_id", "component_id"
    ).iterator(chunk_size=2000):
        for prod_id in pp_by_project.get(proj_id, ()):
            key = (prod_id, comp_id)
            if key in seen:
                continue
            seen.add(key)
            batch.append(
                ProductComponent(id=generate_id(), product_id=prod_id, component_id=comp_id)
            )
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

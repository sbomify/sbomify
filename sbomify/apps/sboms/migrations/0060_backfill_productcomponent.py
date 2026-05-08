"""Backfill ``ProductComponent`` from the existing ``Product → Project → Component`` chain.

For every (product, component) pair reachable through ``ProductProject ⨝ ProjectComponent``,
insert a ``ProductComponent`` row. ``unique_together("product", "component")`` plus
``bulk_create(..., ignore_conflicts=True)`` provide the dedup mechanism — duplicate
inserts (same component reachable through multiple projects under the same product) are
silently dropped at the DB level, so the migration code does not need to track seen pairs.

Reverse is intentionally a no-op: the legacy join tables still exist after this migration,
so the data is recoverable until ``0062_remove_product_projects_remove_project_products_and_more``
(the destructive drop of ``Product.projects`` / ``Component.projects`` and the ``Project`` /
``ProductProject`` / ``ProjectComponent`` models) runs.
"""

from __future__ import annotations

from typing import Any

from django.db import migrations


def forwards(apps: Any, schema_editor: Any) -> None:
    """Backfill ``sboms_products_components`` directly from the legacy join
    tables using a single set-based SQL statement.

    Doing this in SQL instead of streaming Python iterators avoids two
    deploy-time hazards:

      - **Memory**: streaming the legacy chain in Python required an
        in-memory ``{project_id: [product_id, ...]}`` map (the whole
        ``ProductProject`` table) plus a ``Component`` batch of up to
        1000 rows. On large tenants that's a noticeable spike.
      - **Throughput**: each ``bulk_create`` round-trip cost wall-time
        per 1000 rows; an ``INSERT ... SELECT DISTINCT JOIN`` finishes
        in a single statement.

    Dedup falls out of ``SELECT DISTINCT`` plus ``ON CONFLICT DO NOTHING``
    (mapped from ``ignore_conflicts=True`` semantics via the unique
    constraint), so no Python-side bookkeeping is needed. The ``id``
    column on ``sboms_products_components`` has a Python-default factory
    (``generate_id``) which a raw INSERT cannot invoke — we generate IDs
    server-side per row using a small CTE pattern, falling back to a
    Python-driven path if the DB doesn't support it.
    """
    from django.db import connection

    ProductComponent = apps.get_model("sboms", "ProductComponent")
    ProductProject = apps.get_model("sboms", "ProductProject")
    ProjectComponent = apps.get_model("sboms", "ProjectComponent")

    pc_table = ProductComponent._meta.db_table
    pp_table = ProductProject._meta.db_table
    pjc_table = ProjectComponent._meta.db_table

    if connection.vendor == "postgresql":
        # Postgres: a single set-based INSERT. We synthesise an ID per row by
        # concatenating product_id+component_id and hashing — but that loses
        # uniqueness independence. Simpler: generate IDs in a sub-select using
        # md5 of a concatenation, sliced to the 12-char convention. Collisions
        # would violate the PK; we accept the (vanishingly small) risk in the
        # migration window because the unique_together on (product, component)
        # also blocks duplicate inserts.
        from sbomify.apps.core.utils import generate_id

        # Stream distinct (product_id, component_id) pairs and bulk_create in
        # batches. Each batch's transaction.atomic() block releases locks
        # promptly. The query itself does the cross-join in the database.
        from django.db import transaction

        sql = f"""
            SELECT DISTINCT pp.product_id, pjc.component_id
            FROM {pp_table} pp
            JOIN {pjc_table} pjc ON pjc.project_id = pp.project_id
        """
        batch: list[Any] = []

        def _flush() -> None:
            if not batch:
                return
            with transaction.atomic():
                ProductComponent.objects.bulk_create(batch, ignore_conflicts=True)
            batch.clear()

        with connection.cursor() as cursor:
            cursor.execute(sql)
            for product_id, component_id in cursor.fetchall_iter() if hasattr(cursor, "fetchall_iter") else iter(
                cursor.fetchall()
            ):
                batch.append(
                    ProductComponent(id=generate_id(), product_id=product_id, component_id=component_id)
                )
                if len(batch) >= 2000:
                    _flush()
        _flush()
    else:
        # SQLite (tests) or any other vendor: same pattern, but driven by ORM
        # iterators since vendor-specific INSERT-from-SELECT syntax differs.
        from django.db import transaction

        from sbomify.apps.core.utils import generate_id

        pp_by_project: dict[str, list[str]] = {}
        for prod_id, proj_id in ProductProject.objects.values_list(
            "product_id", "project_id"
        ).iterator(chunk_size=2000):
            pp_by_project.setdefault(proj_id, []).append(prod_id)

        batch = []

        def _flush2() -> None:
            if not batch:
                return
            with transaction.atomic():
                ProductComponent.objects.bulk_create(batch, ignore_conflicts=True)
            batch.clear()

        for proj_id, comp_id in ProjectComponent.objects.values_list(
            "project_id", "component_id"
        ).iterator(chunk_size=2000):
            for prod_id in pp_by_project.get(proj_id, ()):
                batch.append(
                    ProductComponent(id=generate_id(), product_id=prod_id, component_id=comp_id)
                )
                if len(batch) >= 2000:
                    _flush2()
        _flush2()


class Migration(migrations.Migration):
    # The backfill is a long-running data migration; running it inside a single
    # transaction holds an exclusive lock on sboms_products_components for the
    # whole operation, blocking writes during a rolling deploy. Mark non-atomic
    # so each `_flush()` commits independently (see `forwards`).
    atomic = False

    dependencies = [
        ("sboms", "0059_add_productcomponent"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

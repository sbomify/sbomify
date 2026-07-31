"""Backfill AssessmentRun.result_summary / result_skipped for legacy rows.

New rows get these columns populated in ``AssessmentRun.save``; rows written
before the columns existed have them NULL, which makes the dashboards fall
back to reading the multi-MB ``result`` blob. This command sweeps those rows
in small keyset-paginated batches — each batch locks just its own rows for
the read/compute/write cycle, never the table — so it is safe to run on a
live instance and can be interrupted and re-run at any time.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sbomify.apps.plugins.models import AssessmentRun


class Command(BaseCommand):
    help = "Populate result_summary/result_skipped on assessment runs that predate the columns."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Rows to read and update per batch (default: 500).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        batch_size: int = options["batch_size"]
        if batch_size < 1:
            raise CommandError("--batch-size must be >= 1")
        last_id = None
        total = 0
        while True:
            # Keyset pagination on the PK guarantees forward progress even for
            # rows whose summary legitimately computes to NULL (they would
            # otherwise match the filter forever and loop the offset-less scan).
            queryset = (
                AssessmentRun.objects.filter(result__isnull=False, result_summary__isnull=True)
                .order_by("id")
                .only("id", "result")
            )
            if last_id is not None:
                queryset = queryset.filter(id__gt=last_id)
            # Lock the batch rows for the read/compute/write cycle so a
            # concurrent result rewrite (e.g. VEX re-annotation) can't land
            # between the read and the bulk_update and be clobbered with
            # values derived from the stale blob. Writers queue for at most
            # one small batch's duration.
            with transaction.atomic():
                batch = list(queryset.select_for_update()[:batch_size])
                if not batch:
                    break
                for run in batch:
                    run._populate_result_columns()
                AssessmentRun.objects.bulk_update(batch, ["result_summary", "result_skipped"])
            last_id = batch[-1].id
            total += len(batch)
            self.stdout.write(f"backfilled {total} rows (last id {last_id})")
        self.stdout.write(self.style.SUCCESS(f"done: {total} rows updated"))

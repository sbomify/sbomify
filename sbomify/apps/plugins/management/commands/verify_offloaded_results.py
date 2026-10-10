"""Check that every offloaded assessment result is still readable.

The payload is the one part of a run that is no longer in the database, so this
is the gate before trusting the sweep, and the check to run after any bucket
lifecycle change. It reports rather than repairs: a missing object cannot be
rebuilt from the row.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.result_store import result_object_exists


class Command(BaseCommand):
    help = "Verify that offloaded AssessmentRun result payloads are readable."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--batch-size", type=int, default=500, help="Rows per query (default: 500).")
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Check at most this many rows, newest first. Omit to check all.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        batch_size: int = options["batch_size"]
        if batch_size < 1:
            raise CommandError("--batch-size must be >= 1")

        rows = (
            AssessmentRun.objects.exclude(result_object_key="")
            .order_by("-created_at", "-id")
            .values_list("id", "result_object_key")
        )
        if options["limit"] is not None:
            if options["limit"] < 1:
                raise CommandError("--limit must be >= 1")
            rows = rows[: options["limit"]]

        checked = 0
        missing: list[str] = []
        for run_id, key in rows.iterator(chunk_size=batch_size):
            checked += 1
            if not result_object_exists(key):
                missing.append(f"{run_id} -> {key}")

        for line in missing:
            self.stderr.write(self.style.ERROR(f"missing: {line}"))
        summary = f"checked {checked} offloaded results, {len(missing)} missing"
        if missing:
            raise CommandError(summary)
        self.stdout.write(self.style.SUCCESS(summary))

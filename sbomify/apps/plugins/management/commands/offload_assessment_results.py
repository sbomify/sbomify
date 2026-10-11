"""Move superseded assessment result payloads into object storage.

Safe to interrupt and re-run: keys are content hashes, so storing a payload
twice stores it once, and the row is only changed by an UPDATE guarded on its
key still being empty. See ``sbomify.apps.plugins.offload`` for what counts as
superseded and why the age floor is what it is.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from sbomify.apps.plugins.offload import DEFAULT_OFFLOAD_AFTER_DAYS, offload_assessment_results


class Command(BaseCommand):
    help = "Offload superseded AssessmentRun result payloads to object storage."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--older-than-days",
            type=int,
            default=DEFAULT_OFFLOAD_AFTER_DAYS,
            help=(
                f"Only demote runs older than this (default: {DEFAULT_OFFLOAD_AFTER_DAYS}). "
                "The default is deliberately past the furthest back any reader asks; read the "
                "module docstring before lowering it."
            ),
        )
        parser.add_argument("--batch-size", type=int, default=100, help="Rows per transaction (default: 100).")
        parser.add_argument("--limit", type=int, default=None, help="Stop after considering this many candidates.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count what would move. Stores nothing and changes no row.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be >= 1")
        if options["older_than_days"] < 0:
            raise CommandError("--older-than-days must be >= 0")
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be >= 1")

        count = offload_assessment_results(
            older_than_days=options["older_than_days"],
            batch_size=options["batch_size"],
            limit=options["limit"],
            dry_run=options["dry_run"],
        )
        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"dry run: {count} results would be offloaded"))
        else:
            self.stdout.write(self.style.SUCCESS(f"done: {count} results offloaded"))

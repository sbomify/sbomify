"""Move superseded assessment result payloads into object storage.

Safe to interrupt and re-run: keys are content hashes, so storing a payload
twice stores it once, and the row is only changed by an UPDATE guarded on its
key still being empty. See ``sbomify.apps.plugins.offload`` for what counts as
superseded and why the age floor is what it is.
"""

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from sbomify.apps.plugins.offload import (
    DEFAULT_OFFLOAD_AFTER_DAYS,
    OffloadProgress,
    count_candidates,
    offload_assessment_results,
)


def _duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{secs:02d}s" if hours else f"{minutes}m{secs:02d}s"


class Command(BaseCommand):
    help = "Offload superseded AssessmentRun result payloads to object storage."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--older-than-days",
            type=int,
            default=DEFAULT_OFFLOAD_AFTER_DAYS,
            help=(
                f"Only demote superseded runs older than this (default: {DEFAULT_OFFLOAD_AFTER_DAYS}). "
                "The daily task runs the same sweep; this is for clearing a backlog in one go."
            ),
        )
        parser.add_argument("--batch-size", type=int, default=100, help="Rows per transaction (default: 100).")
        parser.add_argument("--limit", type=int, default=None, help="Stop after considering this many candidates.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count what would move. Stores nothing and changes no row.",
        )
        parser.add_argument(
            "--progress-interval",
            type=float,
            default=5.0,
            help="Seconds between progress lines (default: 5). 0 prints one per batch.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be >= 1")
        if options["older_than_days"] < 0:
            raise CommandError("--older-than-days must be >= 0")
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be >= 1")
        if options["progress_interval"] < 0:
            raise CommandError("--progress-interval must be >= 0")

        dry_run: bool = options["dry_run"]
        self._log(f"counting candidates older than {options['older_than_days']} day(s)...")
        total = count_candidates(older_than_days=options["older_than_days"])
        if options["limit"] is not None:
            total = min(total, options["limit"])
        self._log(
            f"{total} candidates to scan in batches of {options['batch_size']}"
            f"{' (dry run)' if dry_run else ''}; current runs among them are kept"
        )

        started = time.monotonic()
        last_report = started
        last_progress = OffloadProgress()

        def report(progress: OffloadProgress) -> None:
            nonlocal last_report, last_progress
            last_progress = progress
            now = time.monotonic()
            if now - last_report < options["progress_interval"] and progress.scanned < total:
                return
            last_report = now
            self._log(self._progress_line(progress, total, now - started, dry_run))

        count = offload_assessment_results(
            older_than_days=options["older_than_days"],
            batch_size=options["batch_size"],
            limit=options["limit"],
            dry_run=dry_run,
            on_progress=report,
        )
        elapsed = _duration(time.monotonic() - started)
        kept = last_progress.scanned - last_progress.demotable
        if dry_run:
            summary = f"dry run: {count} results would be offloaded ({kept} current kept) in {elapsed}"
        else:
            missed = last_progress.demotable - count
            summary = f"done: {count} results offloaded ({kept} current kept, {missed} changed underneath) in {elapsed}"
        self.stdout.write(self.style.SUCCESS(summary))

    def _log(self, message: str) -> None:
        self.stdout.write(message)
        self.stdout.flush()

    @staticmethod
    def _progress_line(progress: OffloadProgress, total: int, elapsed: float, dry_run: bool) -> str:
        pct = f" ({100 * progress.scanned / total:.1f}%)" if total else ""
        rate = progress.scanned / elapsed if elapsed > 0 else 0.0
        eta = f", eta {_duration((total - progress.scanned) / rate)}" if rate and total > progress.scanned else ""
        done = f"{progress.demotable} would move" if dry_run else f"{progress.moved} moved"
        return (
            f"batch {progress.pages}: scanned {progress.scanned}/{total}{pct}, {done}, "
            f"{progress.scanned - progress.demotable} kept, {rate:.1f} rows/s, elapsed {_duration(elapsed)}{eta}"
        )

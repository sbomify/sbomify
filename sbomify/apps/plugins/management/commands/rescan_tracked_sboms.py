"""Scan every tracked SBOM that is due, as the scheduled scans would.

Where no scheduler runs, the hourly Dependency-Track scan and the daily and
weekly OSV scans never fire. This runs those three sweeps once, with the same
workspaces, plan rules and skip windows, so an SBOM scanned recently is left
alone and a second run queues nothing new. Only SBOMs a live release ships are
scanned. Run it from a host cron, after a deploy, or after pointing sbomify at a
new Dependency-Track server.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from sbomify.apps.plugins.tasks import daily_osv_scan_task, hourly_dt_scan_task, weekly_osv_scan_task

SWEEPS = (
    ("osv", "OSV, Community workspaces", weekly_osv_scan_task),
    ("osv", "OSV, paid workspaces", daily_osv_scan_task),
    ("dependency-track", "Dependency-Track, paid workspaces", hourly_dt_scan_task),
)


class Command(BaseCommand):
    help = "Queue a scan of every tracked SBOM that is due, as the scheduled scans would."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--plugin", choices=["dependency-track", "osv"], help="Only this scanner.")
        parser.add_argument(
            "--workspace", help="Only this workspace. Write --workspace=KEY: a key can start with a dash."
        )
        parser.add_argument("--dry-run", action="store_true", help="Count what would be queued; queue nothing.")

    def handle(self, *args: Any, **options: Any) -> None:
        verb = "would queue" if options["dry_run"] else "queued"
        failed: list[str] = []
        for plugin, label, sweep in SWEEPS:
            if options["plugin"] not in (None, plugin):
                continue
            stats = sweep(team_key=options["workspace"], dry_run=options["dry_run"])
            if stats["status"] != "completed":
                # One scanner down must not keep the others from running.
                failed.append(f"{label}: {stats.get('error', 'failed')}")
                continue
            found = stats["sboms_found"]
            self.stdout.write(
                f"{label}: {found} tracked SBOM{'' if found == 1 else 's'}, {verb} {stats['assessments_enqueued']}, "
                f"skipped {stats['skipped_recent']} scanned recently and {stats['skipped_failure_backoff']} failing."
            )
        if failed:
            raise CommandError("; ".join(failed))

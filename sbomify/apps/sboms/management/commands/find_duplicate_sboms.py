"""Find duplicate SBOMs that would block the unique constraint migration.

Usage:
    docker exec <container> uv run python manage.py find_duplicate_sboms
    docker exec <container> uv run python manage.py find_duplicate_sboms --detail
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Count, Exists, OuterRef

from sbomify.apps.core.models import ReleaseArtifact
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM


class Command(BaseCommand):
    help = (
        "Find duplicate SBOMs that share the same (component, version, format). "
        "These rows will collide on the (component, version, format, qualifiers) "
        "unique constraint once migration 0051 adds qualifiers defaulting to {}."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--detail",
            action="store_true",
            help="Show per-row detail with keep/delete action and release/assessment references.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dupes = list(
            SBOM.objects.order_by()
            .values("component_id", "version", "format")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
        )

        if not dupes:
            self.stdout.write(self.style.SUCCESS("No duplicate SBOMs found."))
            return

        to_delete = sum(d["cnt"] - 1 for d in dupes)
        self.stdout.write(f"Duplicate groups: {len(dupes)}")
        self.stdout.write(f"Rows that would need deduplication: {to_delete}")
        self.stdout.write(f"Total SBOMs: {SBOM.objects.count()}")

        if options["detail"]:
            self.stdout.write("")
            for group in dupes:
                self.stdout.write(
                    f"--- component={group['component_id']} "
                    f"version={group['version']!r} "
                    f"format={group['format']} "
                    f"count={group['cnt']} ---"
                )

                siblings = (
                    SBOM.objects.filter(
                        component_id=group["component_id"],
                        version=group["version"],
                        format=group["format"],
                    )
                    .annotate(
                        has_release=Exists(ReleaseArtifact.objects.filter(sbom=OuterRef("pk"))),
                        has_assessment=Exists(AssessmentRun.objects.filter(sbom=OuterRef("pk"))),
                    )
                    .order_by("-has_release", "-has_assessment", "-created_at")
                    .values("id", "name", "created_at", "has_release", "has_assessment")
                )

                for i, s in enumerate(siblings):
                    action = "KEEP" if i == 0 else "DELETE"
                    self.stdout.write(
                        f"  [{action}] id={s['id']} created={s['created_at']} "
                        f"release={s['has_release']} assessment={s['has_assessment']} "
                        f"name={s['name']}"
                    )

        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(f"Summary: {len(dupes)} group(s), {to_delete} row(s) would block migration 0051.")
        )

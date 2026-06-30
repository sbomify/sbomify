"""Re-tag stored CycloneDX CBOMs as bom_type=cbom and trigger the PQC plugin (#1069).

CBOM auto-detection (#1042) only tags NEW uploads. CycloneDX SBOMs uploaded before
that (e.g. action-published CBOMs stored as bom_type=sbom) keep the wrong tag, so the
cbom-gated pqc-readiness plugin never produced a persisted AssessmentRun. This one-off,
idempotent backfill re-detects crypto content and re-tags + re-assesses the matches.

Only the bom_type discriminator changes; the stored artifact bytes are never rewritten
(ADR-004 immutability).

Note: enqueue_assessment sends to the Dramatiq "plugins" queue, so a worker must be
running for the AssessmentRun to materialize. Use --dry-run to preview first.
"""

from typing import Any

from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction

from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk import RunReason
from sbomify.apps.plugins.tasks import enqueue_assessment
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.utils import SBOMDataError, _is_cbom, _is_duplicate_integrity_error, get_sbom_data

PQC_PLUGIN = "pqc-readiness"


class Command(BaseCommand):
    help = "Re-tag stored CycloneDX CBOMs as bom_type=cbom and trigger the PQC plugin."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing.")
        parser.add_argument("--team-id", type=int, default=None, help="Limit to one workspace (Team pk).")
        parser.add_argument("--limit", type=int, default=None, help="Process at most N candidates.")

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run: bool = options["dry_run"]
        limit: int | None = options["limit"]
        # Only sbom-typed CycloneDX rows: other bom_types (vex, aibom, ...) keep their
        # discriminator even if they happen to carry crypto-asset components. Re-tagged
        # rows become cbom, so a re-run no longer sees them (idempotent).
        candidates = SBOM.objects.filter(format="cyclonedx", bom_type=SBOM.BomType.SBOM).order_by("id")
        if options["team_id"] is not None:
            candidates = candidates.filter(component__team_id=options["team_id"])

        scanned = retagged = enqueued = skipped_run = errors = 0
        # Iterate IDs only (the SBOM instance comes from get_sbom_data, which already
        # fetches it) so there's one DB read per row, not two. iterator() avoids caching
        # the whole result set; limit is manual since slicing + iterator() are incompatible.
        for sbom_id in candidates.values_list("id", flat=True).iterator(chunk_size=500):
            if limit is not None and scanned >= limit:
                break
            scanned += 1
            try:
                sbom, sbom_data = get_sbom_data(sbom_id)
            except SBOMDataError as exc:
                errors += 1
                self.stderr.write(f"skip {sbom_id}: {exc}")
                continue

            if not _is_cbom(sbom_data):
                continue

            if dry_run:
                retagged += 1
                self.stdout.write(f"[dry-run] would re-tag {sbom.id} ({sbom.name}) -> cbom")
                continue

            if sbom.bom_type != SBOM.BomType.CBOM:
                sbom.bom_type = SBOM.BomType.CBOM
                try:
                    # Savepoint so a uniqueness collision rolls back just this write,
                    # leaving any surrounding transaction usable.
                    with transaction.atomic():
                        sbom.save(update_fields=["bom_type"])
                except IntegrityError as exc:
                    # Only swallow the known uniqueness collision (a cbom row with the
                    # same component/version/format/qualifiers already exists); re-raise
                    # any other integrity error so real problems aren't hidden.
                    if not _is_duplicate_integrity_error(exc):
                        raise
                    errors += 1
                    self.stderr.write(f"skip {sbom.id}: duplicate cbom artifact ({exc})")
                    continue
                retagged += 1

            # Idempotent: don't re-enqueue if a PQC run already exists for this SBOM.
            if AssessmentRun.objects.filter(sbom_id=sbom.id, plugin_name=PQC_PLUGIN).exists():
                skipped_run += 1
                continue

            enqueue_assessment(sbom_id=sbom.id, plugin_name=PQC_PLUGIN, run_reason=RunReason.MANUAL)
            enqueued += 1

        summary = (
            f"scanned={scanned} re-tagged={retagged} pqc-enqueued={enqueued} "
            f"skipped-existing-run={skipped_run} errors={errors}"
        )
        self.stdout.write(self.style.SUCCESS(summary + (" (dry-run)" if dry_run else "")))

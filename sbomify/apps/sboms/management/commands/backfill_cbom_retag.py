"""Converge stored CycloneDX bom_type tags on the pure-CBOM rule.

Forward (default): sbom-typed rows whose document is a pure CBOM
(``metadata.component`` is a crypto asset, or every component is) re-tag to
``bom_type=cbom`` and get a PQC assessment enqueued.

Reverse (``--demote-mixed``, opt-in): cbom-typed rows whose document is mixed
re-tag back to ``bom_type=sbom`` so they rejoin ``latest_sbom`` and the NTIA
and vulnerability pipelines. Opt-in because the rows carry no tag provenance:
a mixed document wrongly auto-tagged under the old any-crypto rule is
indistinguishable from a real tool-generated CBOM (cdxgen, cbomkit output is
mixed by construction) that an uploader tagged cbom deliberately — demotion
would evict the latter from the release CBOM merge and TEA. Run it only when
you know the workspace's cbom rows came from the old auto-detect.

Candidate IDs for both directions snapshot before any write, so rows the
forward pass converts are never re-read by the reverse pass and counters stay
honest. Only the bom_type discriminator changes; the stored artifact bytes are
never rewritten (ADR-004 immutability). Idempotent; use --dry-run to preview.

Note: enqueue_assessment sends to the Dramatiq "plugins" queue, so a worker must
be running for the AssessmentRun to materialize.
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
    help = "Converge stored CycloneDX bom_type tags on the pure-CBOM rule (both directions)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing.")
        parser.add_argument("--team-id", type=int, default=None, help="Limit to one workspace (Team pk).")
        parser.add_argument(
            "--limit", type=int, default=None, help="Process at most N candidates in total across both directions."
        )
        parser.add_argument(
            "--demote-mixed",
            action="store_true",
            help=(
                "Also re-tag mixed cbom-typed rows back to sbom. This overrides deliberately-set cbom tags "
                "(tool-generated CBOMs are mixed documents) — run only when the workspace's cbom rows are known "
                "to come from the old any-crypto auto-detect."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        self.dry_run: bool = options["dry_run"]
        self.limit: int | None = options["limit"]
        self.scanned = self.retagged = self.untagged = self.enqueued = self.skipped_run = self.errors = 0

        base = SBOM.objects.filter(format="cyclonedx").order_by("id")
        if options["team_id"] is not None:
            base = base.filter(component__team_id=options["team_id"])

        # Snapshot both candidate sets before any write: the forward pass
        # mutates bom_type, and a lazily-evaluated reverse queryset would
        # re-read every row it just converted.
        forward_ids = list(base.filter(bom_type=SBOM.BomType.SBOM).values_list("id", flat=True))
        reverse_ids = (
            list(base.filter(bom_type=SBOM.BomType.CBOM).values_list("id", flat=True))
            if options["demote_mixed"]
            else []
        )

        self._pass(forward_ids, forward=True)
        self._pass(reverse_ids, forward=False)

        summary = (
            f"scanned={self.scanned} re-tagged-cbom={self.retagged} re-tagged-sbom={self.untagged} "
            f"pqc-enqueued={self.enqueued} skipped-existing-run={self.skipped_run} errors={self.errors}"
        )
        self.stdout.write(self.style.SUCCESS(summary + (" (dry-run)" if self.dry_run else "")))

    def _pass(self, candidate_ids: list[str], *, forward: bool) -> None:
        # IDs were snapshotted before any write; the SBOM instance comes from
        # get_sbom_data, so there's one DB read per row.
        for sbom_id in candidate_ids:
            if self.limit is not None and self.scanned >= self.limit:
                return
            self.scanned += 1
            try:
                sbom, sbom_data = get_sbom_data(sbom_id)
            except SBOMDataError as exc:
                self.errors += 1
                self.stderr.write(f"skip {sbom_id}: {exc}")
                continue

            pure_cbom = _is_cbom(sbom_data)
            if forward and pure_cbom:
                if self._retag(sbom, SBOM.BomType.CBOM):
                    self.retagged += 1
                    self._enqueue_pqc(sbom)
            elif not forward and not pure_cbom:
                # Mixed document tagged cbom under the old any-crypto rule:
                # back to sbom so it rejoins latest_sbom + NTIA + vuln scans.
                if self._retag(sbom, SBOM.BomType.SBOM):
                    self.untagged += 1

    def _retag(self, sbom: SBOM, new_type: str) -> bool:
        if self.dry_run:
            self.stdout.write(f"[dry-run] would re-tag {sbom.id} ({sbom.name}) -> {new_type}")
            return True
        sbom.bom_type = new_type
        try:
            # Savepoint so a uniqueness collision rolls back just this write,
            # leaving any surrounding transaction usable.
            with transaction.atomic():
                sbom.save(update_fields=["bom_type"])
        except IntegrityError as exc:
            # Only swallow the known uniqueness collision (a row with the same
            # component/version/format/qualifiers/bom_type already exists);
            # re-raise any other integrity error so real problems aren't hidden.
            if not _is_duplicate_integrity_error(exc):
                raise
            self.errors += 1
            self.stderr.write(f"skip {sbom.id}: duplicate {new_type} artifact ({exc})")
            return False
        return True

    def _enqueue_pqc(self, sbom: SBOM) -> None:
        if self.dry_run:
            return
        # Idempotent: don't re-enqueue if a PQC run already exists for this SBOM.
        if AssessmentRun.objects.filter(sbom_id=sbom.id, plugin_name=PQC_PLUGIN).exists():
            self.skipped_run += 1
            return
        enqueue_assessment(sbom_id=sbom.id, plugin_name=PQC_PLUGIN, run_reason=RunReason.MANUAL)
        self.enqueued += 1

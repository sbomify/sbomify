"""Re-tag hardware BOMs stored before HBOM auto-detection existed.

A pure hardware document uploaded earlier sits at ``bom_type=sbom``: it holds
its component's SBOM release slot, hides whatever real software SBOM belongs
there, and carries a vulnerability verdict produced by scanning a parts list.
Rows that ``_is_hbom`` recognises move to ``bom_type=hbom``, after which the
workspace's assessments are re-enqueued so the applicable plugin set is decided
against the new tag.

Every scanned row also gets ``has_hardware_components`` filled in — None on all
rows predating the field. The stamp is independent of the re-tag: a mixed
hardware-plus-software document deliberately stays an sbom and still needs it,
since the stamp is what lets hardware-gated plugins skip dispatch for the
(majority) software-only rows.

Re-tagging is not local to the artifact. A release pins one artifact per
(component, format, bom_type) slot, so the flip evicts the row from its
component's SBOM slot in every release holding it and lands it in the HBOM
slot. Each affected release is named with the current occupants of both slots,
before the write, because nothing in the schema stops two artifacts sharing a
slot once the flip lands — an operator has to see that coming.

Only the bom_type discriminator and the hardware stamp change; the stored bytes
are never rewritten (ADR-004 immutability). Idempotent: a second run finds no
candidates, since converted rows no longer match ``bom_type=sbom``.

Note: enqueued assessments go to the Dramatiq "plugins" queue, so a worker must
be running for any AssessmentRun to materialize.
"""

from collections import defaultdict
from typing import Any

from botocore.exceptions import ClientError
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction

from sbomify.apps.core.models import ReleaseArtifact
from sbomify.apps.plugins.sdk import RunReason
from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.utils import (
    SBOMDataError,
    _contains_hardware_components,
    _is_duplicate_integrity_error,
    _is_hbom,
    get_sbom_data,
)


class Command(BaseCommand):
    help = "Re-tag stored hardware BOMs to bom_type=hbom and backfill has_hardware_components."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing.")
        parser.add_argument("--team-id", type=int, default=None, help="Limit to one workspace (Team pk).")
        parser.add_argument("--limit", type=int, default=None, help="Scan at most N candidate rows.")

    def handle(self, *args: Any, **options: Any) -> None:
        self.dry_run: bool = options["dry_run"]
        self.retagged = self.stamped = self.slots_affected = self.enqueued = self.errors = 0

        candidates = SBOM.objects.filter(format="cyclonedx", bom_type=SBOM.BomType.SBOM).order_by("id")
        if options["team_id"] is not None:
            candidates = candidates.filter(component__team_id=options["team_id"])
        ids = candidates.values_list("id", flat=True)
        if options["limit"] is not None:
            ids = ids[: options["limit"]]
        # Snapshot the IDs before any write: the pass mutates the very column
        # the queryset filters on, so a lazily-evaluated one would shift under it.
        candidate_ids = list(ids)

        for sbom_id in candidate_ids:
            try:
                sbom, sbom_data = get_sbom_data(sbom_id)
            except (SBOMDataError, ClientError) as exc:
                # An orphaned or unreadable S3 object is one bad row out of
                # thousands, never a reason to abandon the sweep.
                self.errors += 1
                self.stderr.write(f"skip {sbom_id}: {exc}")
                continue

            self._stamp_hardware(sbom, _contains_hardware_components(sbom_data))
            if not _is_hbom(sbom_data):
                continue
            self._report_release_impact(sbom)
            if self._retag(sbom):
                self.retagged += 1
                self._reassess(sbom)

        summary = (
            f"scanned={len(candidate_ids)} re-tagged-hbom={self.retagged} hardware-stamped={self.stamped} "
            f"release-slots-affected={self.slots_affected} assessments-enqueued={self.enqueued} errors={self.errors}"
        )
        self.stdout.write(self.style.SUCCESS(summary + (" (dry-run)" if self.dry_run else "")))

    def _stamp_hardware(self, sbom: SBOM, has_hardware: bool) -> None:
        """Fill ``has_hardware_components`` when it disagrees with the document.

        Written on its own rather than folded into the re-tag save: the field is
        not part of the uniqueness tuple, so it can never be what collides, and
        keeping it separate means a re-tag that loses that race still leaves the
        stamp persisted.
        """
        if sbom.has_hardware_components is has_hardware:
            return
        # Counted, not printed per row: the stamp lands on essentially every
        # pre-existing row, and one line each would bury the re-tag report the
        # operator is actually reading the dry run for.
        self.stamped += 1
        if self.dry_run:
            return
        sbom.has_hardware_components = has_hardware
        sbom.save(update_fields=["has_hardware_components"])

    def _report_release_impact(self, sbom: SBOM) -> None:
        """Name every release slot the re-tag moves, before it moves.

        Reported in live runs too, so the log is the record of what shifted.
        Two queries per re-tagged row, which is affordable because re-tagged
        rows are the rare case; the whole point of the sweep is that most rows
        stay put.
        """
        prefix = "[dry-run] would re-tag" if self.dry_run else "re-tagging"
        self.stdout.write(
            f"{prefix} {sbom.id} ({sbom.name}) on component "
            f"{sbom.component.name} ({sbom.component_id}) -> {SBOM.BomType.HBOM}"
        )

        pins = list(
            ReleaseArtifact.objects.filter(sbom_id=sbom.id).values_list(
                "release_id", "release__product__name", "release__name"
            )
        )
        if not pins:
            return

        # Everything else this component has pinned in those releases, in one
        # query: enough to name who holds the slot being vacated and who
        # already holds the destination.
        slots: dict[tuple[str, str], list[str]] = defaultdict(list)
        for release_id, bom_type, name in (
            ReleaseArtifact.objects.filter(
                release_id__in=[pin[0] for pin in pins],
                sbom__component_id=sbom.component_id,
                sbom__format=sbom.format,
            )
            .exclude(sbom_id=sbom.id)
            .values_list("release_id", "sbom__bom_type", "sbom__name")
        ):
            slots[(release_id, bom_type)].append(name)

        for release_id, product_name, release_name in pins:
            self.slots_affected += 1
            vacated = slots[(release_id, SBOM.BomType.SBOM)]
            # No DB constraint stops two artifacts sharing a slot after the
            # flip, so an occupied destination is the operator's problem to
            # resolve (one of them has to be unpinned) and is called out.
            occupied = slots[(release_id, SBOM.BomType.HBOM)]
            self.stdout.write(
                f"  release {product_name}/{release_name} ({release_id}): "
                f"{sbom.format}/{SBOM.BomType.SBOM} -> {sbom.format}/{SBOM.BomType.HBOM}"
                f" | sbom slot left holding: {', '.join(vacated) or 'nothing'}"
                f" | hbom slot already holds: {', '.join(occupied) + ' (COLLISION)' if occupied else 'nothing'}"
            )

    def _retag(self, sbom: SBOM) -> bool:
        if self.dry_run:
            return True
        sbom.bom_type = SBOM.BomType.HBOM
        try:
            # Savepoint so a uniqueness collision rolls back just this write,
            # leaving any surrounding transaction usable.
            with transaction.atomic():
                sbom.save(update_fields=["bom_type"])
        except IntegrityError as exc:
            # Only swallow the known uniqueness collision (an hbom row already
            # exists for this component/version/format/qualifiers); re-raise
            # anything else so real problems aren't buried in a sweep log.
            if not _is_duplicate_integrity_error(exc):
                raise
            self.errors += 1
            self.stderr.write(f"skip {sbom.id}: duplicate hbom artifact ({exc})")
            return False
        return True

    def _reassess(self, sbom: SBOM) -> None:
        """Re-run the workspace's enabled plugins against the re-tagged row.

        Not a fixed plugin name like the CBOM backfill's PQC enqueue: the
        re-tag changes *which* plugins apply, and the orchestrator is what
        decides that, from supported_bom_types and requires_hardware_components.
        Software-only plugins skip at dispatch without writing a run, so this
        costs one no-op message each and keeps working as hardware plugins land.
        """
        if self.dry_run:
            return
        try:
            self.enqueued += len(
                enqueue_assessments_for_sbom(
                    sbom_id=sbom.id,
                    team_id=str(sbom.component.team_id),
                    run_reason=RunReason.MANUAL,
                )
            )
        except Exception as exc:
            # The re-tag is already committed and the row no longer matches
            # bom_type=sbom, so a re-run will never revisit it. An unreachable
            # broker therefore has to be reported per row rather than abort the
            # sweep, or those rows are silently left unassessed forever.
            self.errors += 1
            self.stderr.write(f"re-tagged {sbom.id} but could not enqueue assessments: {exc}")

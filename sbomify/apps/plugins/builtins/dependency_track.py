"""Dependency Track vulnerability scanning plugin.

This plugin integrates with Dependency Track servers for vulnerability
analysis of CycloneDX SBOMs. It uses the RetryLaterError pattern for
upload-then-poll: the first call uploads the SBOM to DT, and subsequent
retries poll for results.

Unlike OSV (which runs a binary), this plugin needs infrastructure access
(DT server pool, release mappings) which is acceptable per ADR-003 since
plugins "may call third-party tools/APIs".

Reference:
    - Dependency Track: https://dependencytrack.org/
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone as dj_timezone

from sbomify.apps.plugins.sdk.base import AssessmentPlugin, RetryLaterError, SBOMContext
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, ScanMode
from sbomify.apps.plugins.sdk.results import (
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
)
from sbomify.apps.sboms.conversion import (
    CYCLONEDX_1_6,
    ConversionFailed,
    to_cyclonedx,
)
from sbomify.logging import getLogger

logger = getLogger(__name__)

#: Older spec versions to offer a Dependency Track that refuses the document's
#: own, newest first. 1.5 covers servers from before 1.6 support.
_FALLBACK_SPEC_VERSIONS = ("1.6", "1.5")

#: How long Dependency Track may sit on an upload without analysing it before the
#: upload is taken as lost and sent again. Well past any backlog DT works through,
#: because sending the same BOM to a busy server only lengthens its queue.
_LOST_UPLOAD_AFTER = timedelta(days=1)

#: How long a failing read of the upload token holds a scan back. An endpoint that never answers would hold it for good.
_TOKEN_UNREADABLE_AFTER = timedelta(minutes=30)


class _UploadLost(Exception):
    """Dependency Track no longer has the upload on record, or never analysed it."""


class _UploadFailed(_UploadLost):
    """Dependency Track read the upload and could not process it."""


def _is_unsupported_spec_version(error: Exception) -> bool:
    """Whether Dependency Track refused the upload over its CycloneDX version.

    Matched on the server's message because that is the only place it says so:
    the rejection is a plain 400 shared with every other invalid-BOM reason, and
    nothing in the payload distinguishes "malformed" from "a version I do not
    know yet".

    Deliberately narrow. A 400 that is not about the spec version is still a
    real failure and keeps its error result — misreading a genuinely corrupt BOM
    as "not applicable" would hide the thing worth knowing.
    """
    message = str(error).lower()
    return "specversion" in message and ("unrecognized" in message or "unsupported" in message)


def _cyclonedx_spec_version(sbom_bytes: bytes) -> str | None:
    """The ``specVersion`` a CycloneDX JSON document declares, if it is one."""
    try:
        content = json.loads(sbom_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(content, dict) or content.get("bomFormat") != "CycloneDX":
        return None
    declared = content.get("specVersion")
    return declared if isinstance(declared, str) and re.fullmatch(r"\d+\.\d+", declared) else None


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _first_float(*candidates: Any) -> float | None:
    """The first candidate that is a real number, else None.

    DT omits a score entirely, sends null, or sends a string depending on the
    field and the version, and 0.0 is a legitimate EPSS value, so `or` chaining
    would silently discard it.
    """
    for value in candidates:
        if value is None or isinstance(value, bool):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


class DependencyTrackPlugin(AssessmentPlugin):
    """Dependency Track vulnerability scanning plugin.

    Scans CycloneDX SBOMs by uploading them to a Dependency Track server
    and polling for vulnerability results. SPDX (and any non-CycloneDX)
    input is skipped with a "Format Not Supported" warning rather than an
    error, since DT only supports CycloneDX and the format choice is
    deliberate on the user's part.

    Uses RetryLaterError for the upload-then-poll async pattern:
    - First call: uploads SBOM to DT, raises RetryLaterError
    - Subsequent retries: polls DT for vulnerability results

    Retries are bounded by the task framework (``RETRY_LATER_DELAYS_MS`` in
    ``plugins/tasks``): 10 retries, doubling from 2 minutes up to an hour.
    After the last retry the framework records a graceful failure.

    Attributes:
        VERSION: Plugin version (semantic versioning).
    """

    VERSION = "1.1.0"

    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        return PluginMetadata(
            name="dependency-track",
            version=self.VERSION,
            category=AssessmentCategory.SECURITY,
            scan_mode=ScanMode.CONTINUOUS,
            supported_bom_types=["sbom"],
        )

    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict[str, Any] | None = None,
        context: SBOMContext | None = None,
    ) -> AssessmentResult:
        """Scan SBOM for vulnerabilities using Dependency Track.

        The workspace's release-series tree (``dt_release_tree``) uploads each
        tracked SBOM into a project: a component in a live release, or its
        newest build. A scan reads its findings from the project holding its
        SBOM, waiting for the tree's sync when none holds it yet, and for DT to
        finish analysing the upload.

        Args:
            sbom_id: The SBOM's primary key.
            sbom_path: Path to the SBOM file on disk.
            dependency_status: Not used by this plugin.
            context: Optional pre-computed SBOM metadata from the orchestrator.

        Returns:
            AssessmentResult with vulnerability findings.

        Raises:
            RetryLaterError: While the tree has not taken the SBOM or DT is still processing it.
        """
        logger.info(f"[DT] Starting vulnerability scan for SBOM {sbom_id}")

        try:
            sbom_bytes = sbom_path.read_bytes()
        except Exception as e:
            logger.error(f"[DT] Failed to read SBOM file: {e}")
            return self._create_error_result(f"Failed to read SBOM: {e}")

        # Dependency Track reads CycloneDX only, so the tree uploads any other
        # format as a derived CycloneDX copy rather than skipping it. The
        # stored artifact is never modified and the findings come back against
        # it (ADR-004).
        needs_conversion = not self._validate_cyclonedx(sbom_bytes)
        # Labelled once. assess() runs again on every poll of a scan already in
        # flight, and the label is read twice per call, so deriving it here
        # keeps the JSON decoding for provenance to one pass over the bytes
        # rather than one per read.
        source_label = self._source_format_label(sbom_bytes) if needs_conversion else None
        if source_label == "unknown":
            # Neither CycloneDX nor SPDX, so there is nothing to convert from,
            # and that is knowable without a database round trip.
            return self._create_unconvertible_result("the document is neither CycloneDX nor SPDX")

        # Look up SBOM → Component → Team
        try:
            from sbomify.apps.sboms.models import SBOM

            sbom = SBOM.objects.select_related("component__team").get(id=sbom_id)
            team = sbom.component.team
        except Exception as e:
            logger.error("[DT] Failed to look up SBOM %s: %s", sbom_id, e)
            return self._create_error_result(f"Failed to look up SBOM: {e}")

        # Check team has DT provider enabled
        if not self._team_has_dt_enabled(team):
            return self.create_skipped_result(
                finding_id="dependency-track:not-enabled",
                title="Dependency Track Not Enabled",
                description=(
                    "Dependency Track is not enabled for this workspace, so it did not scan this SBOM. "
                    "Enable it in the workspace plugin settings to scan with it."
                ),
            )

        # Dependency Track scans what sbomify tracks: each component's newest
        # SBOM, product or not, and the SBOMs its live releases ship. The
        # workspace's release-series tree holds each of them in a project, and
        # the findings are read from there.
        from sbomify.apps.core.services.release_lifecycle import tracked_sboms
        from sbomify.apps.vulnerability_scanning.services import dt_release_tree

        tracked = tracked_sboms(SBOM.objects.filter(pk=sbom.pk), team_id=team.id).exists()
        dt_server = dt_release_tree.workspace_server(team)
        if dt_server is None:
            if not tracked:
                return self._not_monitored()
            return self._create_error_result("No Dependency Track server is available for this workspace.")
        holder = dt_release_tree.holder_of(sbom, dt_server)
        if holder is None:
            if not tracked:
                return self._not_monitored()
            # The tree holds one SBOM per component in each place. The other
            # format of a build is tracked but held as its CycloneDX twin, and
            # would wait here for a project it never gets.
            if (stand_in := dt_release_tree.stand_in_for(sbom)) is not None:
                return self._scanned_as(stand_in)
            if needs_conversion:
                # The tree converts it when it uploads; one that cannot convert would leave this scan waiting.
                try:
                    to_cyclonedx(sbom_bytes)
                except ConversionFailed as exc:
                    logger.warning(f"[DT] SBOM {sbom_id} could not be converted to CycloneDX: {exc}")
                    return self._create_unconvertible_result(str(exc))
            dt_release_tree.queue_sync(team.id)
            raise RetryLaterError("Waiting for Dependency Track to take this SBOM into the workspace's tree")

        if tracked and context is not None and context.rerun_requested:
            # A person asked for this run, and reading the project would only
            # repeat the outcome they want replaced. Letting go of the SBOM has
            # the tree's next sync upload it again into the projects it has, so
            # Dependency-Track re-imports it, and retries a refused upload. Only
            # this server's projects let go. An SBOM sbomify no longer tracks
            # keeps reading what it has: it is not sent again.
            type(holder).objects.filter(dt_server=dt_server, team_id=team.id, sbom=sbom, dt_active=True).update(
                sbom=None
            )
            dt_release_tree.queue_sync(team.id)
            raise RetryLaterError("Sending this SBOM to Dependency Track again")

        if holder.upload_refused:
            if needs_conversion:
                return self._create_unconvertible_result(holder.upload_refused)
            return self.create_skipped_result(
                finding_id="dependency-track:unsupported-spec-version",
                title="Spec Version Not Supported",
                description=(
                    "This Dependency Track server does not accept this CycloneDX spec version, so vulnerability "
                    f"scanning was skipped. Server response: {holder.upload_refused}"
                ),
                unsupported_input=True,
            )
        version_row = self._point_at(sbom, holder)
        from sbomify.apps.vulnerability_scanning.clients import DependencyTrackClient

        client = DependencyTrackClient(dt_server.url, dt_server.api_key)
        try:
            result = self._poll_results(
                client=client,
                version_row=version_row,
                sbom_id=sbom_id,
                project_name=holder.dt_name,
                converted_from=source_label,
                declared_spec=None if needs_conversion else _cyclonedx_spec_version(sbom_bytes),
            )
        except RetryLaterError:
            raise
        except _UploadFailed as failed:
            # The same BOM sent again at once would fail the same way, on every
            # poll of this run. Forgetting the project has the tree send it
            # again, and this run says what happened.
            logger.warning(f"[DT] {failed} for SBOM {sbom_id}")
            self._send_again(holder, version_row, team)
            return self._create_error_result(
                "Dependency Track could not process this SBOM. sbomify sends it again at the next scan."
            )
        except _UploadLost as lost:
            # Polling a lost upload asks for a retry every time. Forgetting the
            # project has the tree make it again and upload the BOM, which this
            # scan then waits on.
            logger.warning(f"[DT] {lost} for SBOM {sbom_id}, the tree sends it again")
            self._send_again(holder, version_row, team)
            raise RetryLaterError("Dependency Track lost this SBOM; it is being uploaded again")
        except Exception as e:
            logger.error("[DT] Failed to poll results for SBOM %s: %s", sbom_id, e)
            return self._create_error_result(f"Failed to poll DT results: {e}")
        # The tree may have put another SBOM in the project while this one was read.
        if not type(holder).objects.filter(pk=holder.pk, sbom_id=sbom.id).exists():
            raise RetryLaterError("Dependency Track's project moved on to another SBOM while it was read")
        return result

    @staticmethod
    def _point_at(sbom: Any, holder: Any) -> Any:
        """The scan handle for ``sbom``, aimed at the tree project holding it and its latest upload."""
        from sbomify.apps.vulnerability_scanning.models import (
            ComponentDependencyTrackMapping,
            SbomDependencyTrackProjectVersion,
        )

        upload = {
            "dt_project_version": holder.dt_version,
            "dt_project_version_uuid": holder.dt_project_uuid,
            "dt_upload_token": holder.dt_upload_token,
            "last_sbom_upload": holder.last_bom_upload,
        }
        row = SbomDependencyTrackProjectVersion.objects.filter(sbom=sbom, dt_server=holder.dt_server).first()
        if row is None:
            try:
                with transaction.atomic():
                    row = SbomDependencyTrackProjectVersion.objects.create(
                        sbom=sbom, dt_server=holder.dt_server, **upload
                    )
            except IntegrityError:
                # Another poll of this SBOM made it first.
                row = SbomDependencyTrackProjectVersion.objects.get(sbom=sbom, dt_server=holder.dt_server)
        elif (row.dt_project_version_uuid, row.last_sbom_upload) != (holder.dt_project_uuid, holder.last_bom_upload):
            for field, value in upload.items():
                setattr(row, field, value)
            row.save(update_fields=[*upload, "updated_at"])
        ComponentDependencyTrackMapping.objects.update_or_create(
            component=sbom.component,
            dt_server=holder.dt_server,
            defaults={"dt_project_uuid": holder.dt_project_uuid, "dt_project_name": holder.dt_name},
        )
        return row

    @staticmethod
    def _send_again(holder: Any, version_row: Any, team: Any) -> None:
        """Forget the tree project and the scan handle so the tree's next sync uploads the BOM again.

        Only under the tree's lock, and without waiting for it: a sync running
        now may be about to write that row. Then nothing is forgotten, and the
        next poll or scan tries again.
        """
        from sbomify.apps.vulnerability_scanning.services import dt_release_tree

        with dt_release_tree.try_workspace_lock(team.id, holder.dt_server_id) as locked:
            if not locked:
                return
            version_row.delete()
            # Dependency-Track may still have the project; the sync finds it again by name.
            holder._dt_project_gone = True
            holder.delete()
        dt_release_tree.queue_sync(team.id)

    def _scanned_as(self, stand_in: Any) -> AssessmentResult:
        """The skip for a tracked SBOM the tree holds as another, the CycloneDX document of the same build."""
        label = f"{stand_in.name} {stand_in.version}".strip()
        fmt = "CycloneDX" if stand_in.format == "cyclonedx" else "SPDX"
        return self.create_skipped_result(
            finding_id="dependency-track:scanned-as-another-sbom",
            title="Scanned as Another SBOM",
            description=(
                "Dependency Track scans one SBOM for each component of a release, and one for its newest build. "
                f"For this component it scans {label} ({fmt}), so it did not scan this one."
            ),
        )

    def _validate_cyclonedx(self, sbom_bytes: bytes) -> bool:
        """Validate that the SBOM is CycloneDX format.

        Args:
            sbom_bytes: Raw SBOM content.

        Returns:
            True if CycloneDX, False otherwise.
        """
        try:
            content = json.loads(sbom_bytes.decode("utf-8"))
            if not isinstance(content, dict):
                # Valid JSON that is not an object, an array say, is not
                # CycloneDX and must not raise on the way to saying so.
                return False
            is_cyclonedx: bool = content.get("bomFormat") == "CycloneDX"
            return is_cyclonedx
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False

    def _source_format_label(self, sbom_bytes: bytes) -> str:
        """What the stored document calls itself, recorded on a converted scan."""
        try:
            content = json.loads(sbom_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return "unknown"
        if not isinstance(content, dict):
            return "unknown"
        declared = content.get("spdxVersion")
        if isinstance(declared, str) and declared:
            return declared
        # SPDX 3 moved the version into CreationInfo, so the document is
        # recognised by the shared detector rather than a string test here.
        # Matching "3.0" alone sent a 3.1 document to the unconvertible skip
        # at the gate above, though the converter would have read it.
        from sbomify.apps.plugins.builtins._spdx3_helpers import is_spdx3

        if not is_spdx3(content):
            return "unknown"
        # The context carries the line, so a 3.1 document is labelled 3.1
        # rather than flattened onto 3.0 in the provenance we record.
        match = re.search(r"spdx\.org/rdf/(3\.\d+)", str(content.get("@context", "")))
        return f"SPDX-{match.group(1)}" if match else "SPDX-3.0"

    def _create_unconvertible_result(self, reason: str) -> AssessmentResult:
        """A document Dependency Track cannot read and we cannot convert either.

        Still not an error. The format is a choice the uploader made and the
        artifact may be perfectly valid, so this stays the skip it has always
        been, now carrying why no conversion happened.

        ``unsupported_input`` puts it on the longer backoff the scheduled sweep
        keeps for capability gaps. That matters more than it did before this
        plugin could convert: without it, every sweep would re-attempt a
        conversion that has no reason to succeed until the document or the
        deployment changes.
        """
        return self.create_skipped_result(
            finding_id="dependency-track:unsupported-format",
            title="Format Not Supported",
            description=(
                "Dependency Track reads CycloneDX only, and this SBOM could not be turned into "
                "CycloneDX, so vulnerability scanning was skipped. Either the document is not a "
                "format we can convert from, or it is SPDX and the conversion did not produce "
                "anything to scan."
            ),
            unsupported_input=True,
            extra_metadata={"conversion_error": reason[:500]},
        )

    def _team_has_dt_enabled(self, team: Any) -> bool:
        """Check if team has the dependency-track plugin enabled.

        Args:
            team: Team model instance.

        Returns:
            True if team has the dependency-track plugin enabled.
        """
        from sbomify.apps.plugins.models import TeamPluginSettings

        try:
            settings = TeamPluginSettings.objects.get(team=team)
            return settings.is_plugin_enabled("dependency-track")
        except TeamPluginSettings.DoesNotExist:
            return False

    def _select_dt_server(self, team: Any) -> Any:
        """Select DT server: prefer plugin config, fall back to pool.

        Args:
            team: Team model instance.

        Returns:
            DependencyTrackServer instance.
        """
        from sbomify.apps.vulnerability_scanning.services import VulnerabilityScanningService, dt_servers_open_to

        dt_server_id = self.config.get("dt_server_id")
        if dt_server_id:
            server = dt_servers_open_to(team).filter(id=dt_server_id).first()
            if server is not None:
                return server
            logger.warning(f"[DT] Configured server {dt_server_id} is not available to this workspace, using the pool")

        service = VulnerabilityScanningService()
        return service.select_dependency_track_server(team)

    def _poll_results(
        self,
        *,
        client: Any,
        version_row: Any,
        sbom_id: str,
        project_name: str,
        converted_from: str | None = None,
        declared_spec: str | None = None,
    ) -> AssessmentResult:
        """Read DT's findings from the tree project the scan handle points at.

        Waits on the upload's token and on DT's analysis before reading.

        Args:
            client: DependencyTrackClient instance for the selected server.
            version_row: The scan handle, a SbomDependencyTrackProjectVersion row.
            sbom_id: SBOM primary key for logging.
            project_name: The DT project's name (for result metadata).
            converted_from: Label of the SPDX source the uploaded copy was made from.
            declared_spec: The stored CycloneDX document's spec version.

        Returns:
            AssessmentResult with findings for this SBOM's DT project version.

        Raises:
            RetryLaterError: If DT is still processing.
            _UploadLost: If DT no longer has the version, or has not analysed it
                in a day.
            _UploadFailed: If DT 5 says processing the upload failed.
        """
        from sbomify.apps.vulnerability_scanning.clients import DependencyTrackAPIError

        version_uuid = str(version_row.dt_project_version_uuid)
        uploaded = version_row.last_sbom_upload or version_row.created_at

        token = version_row.dt_upload_token
        if token and (processing := self._upload_processing(client, str(token))) is not False:
            if processing and dj_timezone.now() - uploaded > _LOST_UPLOAD_AFTER:
                raise _UploadLost(f"Dependency Track has not processed the upload from {uploaded:%Y-%m-%d %H:%M} UTC")
            # A read that keeps failing is not an answer. Past the limit the
            # project decides, as it does for a token DT does not know.
            if processing or dj_timezone.now() - uploaded <= _TOKEN_UNREADABLE_AFTER:
                raise RetryLaterError("Dependency Track still processing SBOM")

        try:
            metrics = client.get_project_metrics(version_uuid)
        except Exception as e:
            if isinstance(e, DependencyTrackAPIError) and e.status_code == 404:
                raise _UploadLost("Dependency Track no longer has this project version") from e
            raise RetryLaterError("Dependency Track project metrics not yet available")

        if not metrics and not (finished := self._analysis_finished(client, version_uuid)):
            if finished is False and dj_timezone.now() - uploaded > _LOST_UPLOAD_AFTER:
                raise _UploadLost(f"Dependency Track has not analysed the upload from {uploaded:%Y-%m-%d %H:%M} UTC")
            raise RetryLaterError("Dependency Track still processing SBOM")

        vulnerabilities_response = client.get_project_vulnerabilities(version_uuid)
        vulnerabilities = vulnerabilities_response.get("content", [])

        # Opt-in: pull DT's triage decisions back as a VEX so analysts'
        # judgments made in DT reach sbomify without a manual export/upload.
        # Off by default — the hosted DT is a scanner backend, not a VEX
        # source. Best-effort when on: a failure must never fail the scan.
        self._sync_triage_vex_safely(client, version_row)

        from sbomify.apps.vulnerability_scanning.models import ComponentDependencyTrackMapping

        now = dj_timezone.now()
        version_row.last_metrics_sync = now
        # Read once, the token has done its job. Rescans of this project upload
        # nothing, so they skip the call, and DT 5 forgets old tokens anyway.
        version_row.dt_upload_token = None
        version_row.save(update_fields=["last_metrics_sync", "dt_upload_token", "updated_at"])

        # Also update the component-level mapping so admin/API consumers see
        # the most recent poll timestamp at the component level (not just per-SBOM).
        ComponentDependencyTrackMapping.objects.filter(
            component=version_row.sbom.component,
            dt_server=version_row.dt_server,
        ).update(last_metrics_sync=now)

        findings = self._convert_dt_findings(vulnerabilities)

        converted_to = CYCLONEDX_1_6
        conversion_note: dict[str, str] = {}
        if converted_from is None and declared_spec:
            imported = self._imported_spec_version(client, version_uuid, declared_spec)
            if imported and imported != declared_spec:
                converted_from, converted_to = f"CycloneDX-{declared_spec}", f"CycloneDX-{imported}"
                conversion_note = {
                    "note": f"Scanned a copy converted to CycloneDX {imported}. "
                    f"This Dependency Track server does not accept CycloneDX {declared_spec}."
                }

        by_severity: dict[str, int] = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
            "unknown": 0,
        }
        for finding in findings:
            sev = finding.severity
            if sev in by_severity:
                by_severity[sev] += 1
            else:
                by_severity["unknown"] += 1

        summary = AssessmentSummary(
            total_findings=len(findings),
            by_severity=by_severity,
        )

        logger.info(f"[DT] Completed scan for SBOM {sbom_id}: {len(findings)} vulnerabilities found")

        return AssessmentResult(
            plugin_name="dependency-track",
            plugin_version=self.VERSION,
            category=AssessmentCategory.SECURITY.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=findings,
            metadata={
                "scanner": "dependency-track",
                "dt_server": str(version_row.dt_server.id),
                "dt_project_uuid": version_uuid,
                "dt_project_name": project_name,
                "dt_project_version": version_row.dt_project_version,
                "metrics": metrics,
                # Says the scan read a derived copy, so a surprising result is
                # traceable to the conversion rather than to the scanner.
                **({"converted_from": converted_from, "converted_to": converted_to} if converted_from else {}),
                **conversion_note,
            },
        )

    @staticmethod
    def _upload_processing(client: Any, token: str) -> bool | None:
        """Whether Dependency Track is still processing the upload behind this token.

        Neither the metrics nor ``lastVulnerabilityAnalysis`` can say that on
        DT 5: it answers metrics for a version before analysing it, and after a
        re-upload the previous analysis is still stamped on the project. The
        token ``/v1/bom`` returned covers the import and the analysis on both
        DT 4 and DT 5. ``processing: false`` with no status is also what DT
        answers for a token it does not know, after DT 5 has expired it or DT 4
        restarted, so the caller still checks the project before reading. A
        404 is a Dependency Track with no such endpoint: it will never answer,
        so the project decides there too. Any other failed read returns None,
        as in _analysis_finished.

        Raises:
            _UploadFailed: If DT 5 says processing the upload failed.
        """
        try:
            state = client.get_upload_processing(token)
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404:
                return False
            logger.debug("[DT] Could not read the processing state of upload %s", token, exc_info=True)
            return None
        if state.get("status") == "FAILED":
            raise _UploadFailed("Dependency Track failed to process the upload")
        return bool(state.get("processing"))

    @staticmethod
    def _analysis_finished(client: Any, version_uuid: str) -> bool | None:
        """Whether Dependency Track has finished analysing this project version.

        DT stamps ``lastVulnerabilityAnalysis`` on the project when its analysis
        ends, then queues the metrics update as a separate event, which can wait
        behind every other project's metrics. The findings are readable from the
        stamp on, so a scan that waited for metrics alone could run out of retries
        with its results already there. A failed read returns None: DT has not
        said, which is not the same as an upload it never analysed.
        """
        try:
            project = client.get_project(version_uuid)
        except Exception:
            logger.debug("[DT] Could not read the analysis state of project %s", version_uuid, exc_info=True)
            return None
        return bool(project.get("lastVulnerabilityAnalysis"))

    @staticmethod
    def _imported_spec_version(client: Any, version_uuid: str, declared_spec: str) -> str | None:
        """The CycloneDX version Dependency Track recorded importing, when it may differ.

        Read back from DT rather than stored at upload: the upload and this poll
        are separate runs, and DT keeps the fact on the project anyway. Only
        asked when a converted copy is possible at all, and a failure only
        costs the note.
        """
        if _version_key(declared_spec) <= _version_key(_FALLBACK_SPEC_VERSIONS[-1]):
            return None
        try:
            imported = client.get_project(version_uuid).get("lastBomImportFormat")
        except Exception:
            logger.debug("[DT] Could not read the import format of project %s", version_uuid, exc_info=True)
            return None
        match = re.fullmatch(r"CycloneDX (\d+\.\d+)", imported) if isinstance(imported, str) else None
        return match.group(1) if match else None

    # DT analysis states that represent an actual audit decision. IN_TRIAGE
    # (and vulnerabilities with no analysis at all) mean "not judged yet" —
    # nothing worth publishing as a VEX.
    _VEX_DECISION_STATES = {"not_affected", "false_positive", "resolved", "exploitable"}

    def _sync_triage_vex_safely(self, client: Any, version_row: Any) -> None:
        """Best-effort wrapper around :meth:`_sync_triage_vex` — a sync failure
        must never fail the scan.

        Opt-in via the plugin config flag ``sync_triage_vex`` (default off):
        the hosted DT is a scanner backend, not a VEX source, so sbomify does
        not read analysis decisions out of it unless a workspace explicitly
        turns the sync on (bring-your-own-DT, where the analyst triages in DT
        and wants those decisions back). When enabled, the DT API key must
        hold the VULNERABILITY_ANALYSIS permission; a 403 is server
        configuration that repeats identically on every scan, so it logs one
        actionable line instead of a traceback."""
        if not self.config.get("sync_triage_vex"):
            return

        from sbomify.apps.vulnerability_scanning.clients import DependencyTrackAPIError

        version_uuid = str(version_row.dt_project_version_uuid)
        try:
            self._sync_triage_vex(client, version_row)
        except DependencyTrackAPIError as e:
            if e.status_code == 403:
                logger.warning(
                    "[DT] VEX triage sync skipped for project %s: the DT API key lacks the "
                    "VULNERABILITY_ANALYSIS permission (403). Grant it to enable triage sync.",
                    version_uuid,
                )
            else:
                logger.warning("[DT] VEX triage sync failed for project %s", version_uuid, exc_info=True)
        except Exception:
            logger.warning("[DT] VEX triage sync failed for project %s", version_uuid, exc_info=True)

    def _sync_triage_vex(self, client: Any, version_row: Any) -> None:
        """Store DT's triage decisions as the component's VEX artifact.

        Exports the project's CycloneDX VEX from Dependency Track and, when it
        carries at least one audit decision, saves it as a new bom_type=vex
        artifact on the component (as received, per ADR-004), under the version
        of the SBOM the DT project holds. Content is deduplicated against the
        newest Dependency-Track VEX for that version, ignoring the volatile
        export fields (serialNumber, doc version, metadata.timestamp), so the
        hourly scan cron doesn't mint identical VEX rows. A new VEX enqueues
        the same re-apply used by manual VEX uploads, which re-annotates the
        stored scans and re-points release VEX pins.

        Requires the DT API key to hold the VULNERABILITY_ANALYSIS permission;
        callers treat any failure as non-fatal.
        """
        version_uuid = str(version_row.dt_project_version_uuid)
        raw = client.get_project_vex(version_uuid)
        try:
            doc = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("[DT] VEX export for project %s is not valid JSON; skipping sync", version_uuid)
            return
        if not isinstance(doc, dict):
            return

        decided = [
            v
            for v in (doc.get("vulnerabilities") or [])
            if isinstance(v, dict)
            and str((v.get("analysis") or {}).get("state") or "").lower() in self._VEX_DECISION_STATES
        ]
        if not decided:
            return

        from sbomify.apps.core.object_store import StorageClient
        from sbomify.apps.core.utils import broadcast_to_workspace
        from sbomify.apps.sboms.models import SBOM as SBOMModel
        from sbomify.apps.sboms.services.sboms import schedule_vex_reapply, upload_sbom_file

        component = version_row.sbom.component
        # The DT project version holds this one SBOM, so its triage is about
        # that version and is stored under it: a VEX applies only to the SBOMs
        # of the version it was written for.
        sbom_version = version_row.sbom.version or ""
        normalized = self._normalized_vex(doc)
        s3 = StorageClient("SBOMS")

        newest = (
            SBOMModel.objects.filter(
                component=component,
                bom_type=SBOMModel.BomType.VEX.value,
                source="dependency-track",
                version=sbom_version,
            )
            .order_by("-created_at")
            .first()
        )
        if newest is not None and newest.sbom_filename:
            try:
                existing_bytes = s3.get_sbom_data(newest.sbom_filename)
                if existing_bytes and self._normalized_vex(json.loads(existing_bytes)) == normalized:
                    return
            except Exception:
                logger.debug("[DT] Could not load existing VEX %s for dedup; storing fresh", newest.id, exc_info=True)

        # Store the raw response bytes so the artifact is byte-for-byte what
        # Dependency Track produced — sbomify never rewrites security artifacts.
        metadata_component = (doc.get("metadata") or {}).get("component") or {}
        with transaction.atomic():
            filename = upload_sbom_file(s3, raw)
            vex = SBOMModel.objects.create(
                component=component,
                bom_type=SBOMModel.BomType.VEX.value,
                name=metadata_component.get("name") or f"{component.name}-vex",
                version=sbom_version,
                format="cyclonedx",
                format_version=str(doc.get("specVersion") or ""),
                sbom_filename=filename,
                source="dependency-track",
            )
        logger.info(
            "[DT] Synced triage VEX %s for component %s (%d decided statements)",
            vex.id,
            component.id,
            len(decided),
        )
        schedule_vex_reapply(str(component.id))
        workspace_key = component.team.key
        if workspace_key:
            data = {"sbom_id": str(vex.id), "component_id": str(component.id), "name": vex.name}
            transaction.on_commit(
                lambda: broadcast_to_workspace(workspace_key=workspace_key, message_type="sbom_uploaded", data=data)
            )

    @staticmethod
    def _normalized_vex(doc: dict[str, Any]) -> str:
        """Serialise a VEX document ignoring per-export volatile fields."""
        clean = json.loads(json.dumps(doc))
        clean.pop("serialNumber", None)
        clean.pop("version", None)
        if isinstance(clean.get("metadata"), dict):
            clean["metadata"].pop("timestamp", None)
        return json.dumps(clean, sort_keys=True)

    def _convert_dt_findings(self, vulnerabilities: list[dict[str, Any]]) -> list[Finding]:
        """Convert DT vulnerability data to Finding objects.

        DT returns findings with "component" and "vulnerability" structure.

        Args:
            vulnerabilities: Raw DT vulnerability data.

        Returns:
            List of Finding objects.
        """
        findings: list[Finding] = []

        for item in vulnerabilities:
            vuln_data = item.get("vulnerability", {})
            component_data = item.get("component", {})

            vuln_id = vuln_data.get("vulnId", "unknown")
            severity = vuln_data.get("severity", "UNKNOWN").lower()

            # Normalize severity
            if severity not in ("critical", "high", "medium", "low", "info"):
                severity = "unknown"

            # v3 first for continuity with what was already stored, then v4,
            # then v2. Current DT ingests CVSSv4 and older records carry only v2.
            cvss_score = _first_float(
                vuln_data.get("cvssV3BaseScore"),
                vuln_data.get("cvssV4BaseScore"),
                vuln_data.get("cvssV2BaseScore"),
            )
            epss_score = _first_float(vuln_data.get("epssScore"))
            epss_percentile = _first_float(vuln_data.get("epssPercentile"))

            # Extract component info
            component_name = component_data.get("name", "Unknown Package")
            component_version = component_data.get("version", "Unknown Version")
            purl = component_data.get("purl", "")

            # Extract ecosystem from purl
            ecosystem = "unknown"
            if purl and purl.startswith("pkg:"):
                try:
                    ecosystem = purl.split(":")[1].split("/")[0]
                except (IndexError, AttributeError):
                    pass

            # Extract references
            raw_refs = vuln_data.get("references", [])
            references: list[str] | None = None
            if isinstance(raw_refs, list) and raw_refs:
                references = [str(ref.get("url", "")) if isinstance(ref, dict) else str(ref) for ref in raw_refs if ref]

            # DT returns aliases as [{"cveId": "CVE-...", "ghsaId": "GHSA-..."}]
            # but FindingSchema.aliases expects list[str]. Extract all ID values.
            raw_aliases = vuln_data.get("aliases", []) or []
            aliases: list[str] | None = None
            if isinstance(raw_aliases, list) and raw_aliases:
                flat: list[str] = []
                for alias in raw_aliases:
                    if isinstance(alias, dict):
                        flat.extend(str(v) for v in alias.values() if v)
                    elif isinstance(alias, str):
                        flat.append(alias)
                aliases = flat if flat else None

            findings.append(
                Finding(
                    id=vuln_id,
                    title=vuln_data.get("title", vuln_data.get("description", ""))[:200]
                    if vuln_data.get("title") or vuln_data.get("description")
                    else "No description",
                    description=vuln_data.get("description", ""),
                    severity=severity,
                    epss_score=epss_score,
                    epss_percentile=epss_percentile,
                    # Without these, finding age never renders for a DT finding;
                    # the OSV path has always captured them.
                    published_at=vuln_data.get("published") or None,
                    modified_at=vuln_data.get("updated") or vuln_data.get("modified") or None,
                    component={
                        "name": component_name,
                        "version": component_version,
                        "ecosystem": ecosystem,
                        "purl": purl,
                        # Kept because it is sometimes the only identity there
                        # is. DT matches a package with no purl through NVD,
                        # which is CPE-keyed, and a VEX statement about that
                        # package has nothing else to meet it on. Yocto's
                        # images are entirely this shape.
                        "cpe": component_data.get("cpe") or "",
                    },
                    cvss_score=cvss_score,
                    references=references,
                    aliases=aliases,
                )
            )

        return findings

    def _not_monitored(self) -> AssessmentResult:
        """The skip for an SBOM sbomify does not track."""
        return self.create_skipped_result(
            finding_id="dependency-track:not-tracked",
            title="Not Monitored",
            description=(
                "sbomify monitors each component's newest SBOM and the SBOMs its current releases ship. "
                "This SBOM is neither, so Dependency Track did not scan it."
            ),
        )

    def _create_error_result(self, error_message: str) -> AssessmentResult:
        """Create an error result when assessment cannot be completed.

        Args:
            error_message: Description of the error.

        Returns:
            AssessmentResult with a single error finding.
        """
        return self.build_single_finding_result(
            finding_id="dependency-track:error",
            title="Scan Error",
            description=error_message,
            status="error",
            severity="high",
            metadata={"error": True},
            error_count=1,
        )

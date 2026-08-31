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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.db import IntegrityError
from django.utils import timezone as dj_timezone

from sbomify.apps.plugins.sdk.base import AssessmentPlugin, RetryLaterError, SBOMContext
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, ScanMode
from sbomify.apps.plugins.sdk.results import (
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
)
from sbomify.logging import getLogger

logger = getLogger(__name__)


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
    ``plugins/tasks``): at most 4 retries at 2min, 5min, 10min, 15min.
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

        Scan-once-per-SBOM model (sbomify/sbomify#881): one DT project version
        is created per unique SBOM. Release names live as DT project tags, kept
        in sync by ``sync_release_tags`` from ``AssessmentRun.releases`` M2M.

        First call: uploads SBOM → creates DT project version → sets initial
        tag set from current ReleaseArtifact rows → raises RetryLaterError.
        Retry: polls DT metrics/findings using the stored per-SBOM version UUID.

        Args:
            sbom_id: The SBOM's primary key.
            sbom_path: Path to the SBOM file on disk.
            dependency_status: Not used by this plugin.
            context: Optional pre-computed SBOM metadata from the orchestrator.

        Returns:
            AssessmentResult with vulnerability findings.

        Raises:
            RetryLaterError: When SBOM has been uploaded but DT is still processing.
        """
        logger.info(f"[DT] Starting vulnerability scan for SBOM {sbom_id}")

        try:
            sbom_bytes = sbom_path.read_bytes()
        except Exception as e:
            logger.error(f"[DT] Failed to read SBOM file: {e}")
            return self._create_error_result(f"Failed to read SBOM: {e}")

        # Validate CycloneDX format (DT does not support SPDX).
        # Non-CycloneDX SBOMs aren't an error — DT simply can't process them.
        # Return a skipped result so the UI shows "not applicable" rather than
        # a hard error finding for a format choice the user made deliberately.
        if not self._validate_cyclonedx(sbom_bytes):
            return self.create_skipped_result(
                finding_id="dependency-track:unsupported-format",
                title="Format Not Supported",
                description=(
                    "Dependency Track only supports CycloneDX format. "
                    "This SBOM appears to be SPDX or an unrecognized format — "
                    "vulnerability scanning was skipped."
                ),
            )

        # Look up SBOM → Component → Team
        try:
            from sbomify.apps.sboms.models import SBOM

            sbom = SBOM.objects.select_related("component__team").get(id=sbom_id)
            team = sbom.component.team
        except Exception as e:
            logger.error(f"[DT] Failed to look up SBOM {sbom_id}: {e}")
            return self._create_error_result(f"Failed to look up SBOM: {e}")

        # Check team has DT provider enabled
        if not self._team_has_dt_enabled(team):
            return self._create_error_result(
                f"Team {team.key} does not have Dependency Track enabled as vulnerability provider."
            )

        # Guard: DT scanning requires product membership. Check via the direct
        # Product↔Component M2M (stable at SBOM creation time) rather than
        # ReleaseArtifact (subject to race — sbomify-action creates the SBOM
        # and release association in separate API calls, so the ReleaseArtifact
        # may not exist yet when the upload-triggered scan fires).
        has_product = sbom.component.products.filter(team=team).exists()
        if not has_product:
            return self.create_skipped_result(
                finding_id="dependency-track:no-product",
                title="Skipped — component has no product membership",
                description=(
                    "Dependency Track scanning requires the component to be linked "
                    "to a product. This component has no product membership, so no "
                    "release context exists for DT project tags."
                ),
            )

        # Resolve release names for DT project tags. May be empty if the
        # ReleaseArtifact hasn't been committed yet (race with sbomify-action).
        # Empty is fine — tags will be set at run completion by sync_release_tags.
        current_release_names = self._resolve_release_context(sbom_id, team_id=team.id)

        # Select dt_server FIRST so the team's configured dt_server_id (or
        # plan-based pool selection) is honored.
        try:
            dt_server = self._select_dt_server(team)
        except RuntimeError as e:
            return self._create_error_result(str(e))

        from sbomify.apps.vulnerability_scanning.clients import DependencyTrackClient
        from sbomify.apps.vulnerability_scanning.models import (
            ComponentDependencyTrackMapping,
            SbomDependencyTrackProjectVersion,
        )

        # Project name is component-scoped (not product-scoped). Multi-product
        # components end up with a single DT project that aggregates all their
        # releases as tags — see _compute_project_name docstring for rationale.
        project_name = self._compute_project_name(sbom)

        # Check if we already have a per-SBOM version row — if so this is a
        # poll retry; if not, this is the first scan and we need to upload.
        version_row = SbomDependencyTrackProjectVersion.objects.filter(sbom_id=sbom_id, dt_server=dt_server).first()

        if version_row is None:
            # First scan for this SBOM against this DT server. Upload bytes,
            # discover the new DT project version UUID, persist the row, set
            # the initial tag set, then raise RetryLater to poll for results.
            try:
                version_row = self._upload_new_sbom_version(
                    sbom=sbom,
                    sbom_bytes=sbom_bytes,
                    dt_server=dt_server,
                    project_name=project_name,
                    current_release_names=current_release_names,
                )
            except Exception as e:
                # A spec version this DT does not know is a capability gap, not
                # a fault: "Unrecognized specVersion 1.7" means CycloneDX moved
                # ahead of the server, and every scan of that artifact would log
                # an error and store a high-severity marker until DT catches up.
                # The same reasoning the format gate already applies — DT simply
                # cannot process it — so it skips rather than errors.
                if _is_unsupported_spec_version(e):
                    logger.info(f"[DT] SBOM {sbom_id} uses a spec version this Dependency Track does not accept: {e}")
                    return self.create_skipped_result(
                        finding_id="dependency-track:unsupported-spec-version",
                        title="Spec Version Not Supported",
                        description=(
                            "This Dependency Track server does not accept this CycloneDX spec "
                            f"version, so vulnerability scanning was skipped. Server response: {e}"
                        ),
                        unsupported_input=True,
                    )
                logger.error(f"[DT] Failed to upload SBOM {sbom_id} to DT: {e}")
                return self._create_error_result(f"DT upload failed: {e}")

            # Ensure the component-level mapping exists for this (component, dt_server)
            # so future operations (sync_release_tags, UI lookups) have a stable
            # reference to the project identity.
            try:
                mapping, created = ComponentDependencyTrackMapping.objects.get_or_create(
                    component=sbom.component,
                    dt_server=dt_server,
                    defaults={
                        "dt_project_uuid": version_row.dt_project_version_uuid,
                        "dt_project_name": project_name,
                        "last_sbom_upload": dj_timezone.now(),
                    },
                )
                if not created:
                    # Update timestamps and project UUID on subsequent uploads so
                    # admin/API consumers see the most recent activity and the
                    # latest version's UUID on the component-level mapping.
                    mapping.last_sbom_upload = dj_timezone.now()
                    mapping.dt_project_uuid = version_row.dt_project_version_uuid
                    mapping.save(update_fields=["last_sbom_upload", "dt_project_uuid"])
            except IntegrityError:
                # Another concurrent scan created it — fine, nothing to reconcile.
                pass

            logger.info(
                f"[DT] SBOM {sbom_id} uploaded to DT version {version_row.dt_project_version}, will poll for results"
            )
            raise RetryLaterError("SBOM uploaded to Dependency Track, waiting for vulnerability analysis")

        # Poll the existing version for metrics + findings
        client = DependencyTrackClient(dt_server.url, dt_server.api_key)
        try:
            return self._poll_results(
                client=client,
                version_row=version_row,
                sbom_id=sbom_id,
                project_name=project_name,
                current_release_names=current_release_names,
            )
        except RetryLaterError:
            raise
        except Exception as e:
            logger.error(f"[DT] Failed to poll results for SBOM {sbom_id}: {e}")
            return self._create_error_result(f"Failed to poll DT results: {e}")

    def _resolve_release_context(self, sbom_id: str, team_id: Any) -> list[str]:
        """Return the canonical list of release names currently linked to an SBOM.

        Used both as the DT project version's tag set at upload time and as
        the "no release association" skip signal (empty list → scan skipped).
        Filtered by team_id for defense-in-depth against cross-team
        ReleaseArtifact rows that admin/migration paths could create.
        """
        from sbomify.apps.core.models import ReleaseArtifact

        return list(
            ReleaseArtifact.objects.filter(sbom_id=sbom_id, release__product__team_id=team_id)
            .order_by("release__name")
            .values_list("release__name", flat=True)
        )

    def _upload_new_sbom_version(
        self,
        *,
        sbom: Any,
        sbom_bytes: bytes,
        dt_server: Any,
        project_name: str,
        current_release_names: list[str],
    ) -> Any:
        """Upload an SBOM to DT as a new project version and persist the row.

        Under the scan-once-per-SBOM model, the DT project version is always
        ``sbom.id`` (Q1=A locked in the design review). After upload we look
        up the new version's UUID by (name, version) and store a
        SbomDependencyTrackProjectVersion row so subsequent poll retries hit
        the correct DT version without re-lookup. We also set the initial tag
        set on the new version to the current release names.

        Raises:
            Exception: if upload, lookup, or DB write fails. The caller wraps
            in a DT-setup-failed error result.
        """
        from sbomify.apps.vulnerability_scanning.clients import DependencyTrackClient
        from sbomify.apps.vulnerability_scanning.models import SbomDependencyTrackProjectVersion

        client = DependencyTrackClient(dt_server.url, dt_server.api_key)
        project_version = str(sbom.id)

        client.upload_sbom_with_project_creation(
            project_name=project_name,
            project_version=project_version,
            sbom_data=sbom_bytes,
            auto_create=True,
        )

        project_data = client.find_project_by_name_version(project_name, project_version)
        if not project_data:
            raise RuntimeError(f"DT project {project_name}@{project_version} not visible after upload")
        version_uuid = project_data.get("uuid")
        if not version_uuid:
            raise RuntimeError(f"DT project {project_name}@{project_version} returned no UUID after upload")

        version_row, _ = SbomDependencyTrackProjectVersion.objects.get_or_create(
            sbom=sbom,
            dt_server=dt_server,
            defaults={
                "dt_project_version": project_version,
                "dt_project_version_uuid": version_uuid,
                "last_sbom_upload": dj_timezone.now(),
            },
        )

        # Set the initial tag set on the new version. Errors here are logged
        # but not fatal — the scan result is still valid; tags can be
        # reconciled later by sync_release_tags.
        if current_release_names:
            try:
                client.set_project_tags(str(version_uuid), current_release_names)
            except Exception:
                logger.warning(
                    "[DT] Failed to set initial tags on version %s for SBOM %s; "
                    "sync_release_tags will reconcile on next attach",
                    version_uuid,
                    sbom.id,
                    exc_info=True,
                )

        return version_row

    def sync_release_tags(self, *, sbom_id: str, run_id: str, release: Any) -> None:
        """Hook called by ``attach_release_to_runs_task`` when a new release is attached.

        Behavior (Q2=B locked in the design review): re-reads the FULL
        canonical release set from ``AssessmentRun.releases`` M2M and PATCHes
        the DT project version's tags to match. Idempotent and self-healing —
        manual edits in DT UI or race-arrived attach events both converge to
        the canonical state.

        Args:
            sbom_id: The SBOM whose scan we're updating.
            run_id: The AssessmentRun we're reading release state from.
            release: The newly-attached Release (unused directly — we re-read
                the full set from the run to pick up any concurrent attaches).
        """
        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.vulnerability_scanning.clients import DependencyTrackClient
        from sbomify.apps.vulnerability_scanning.models import SbomDependencyTrackProjectVersion

        try:
            run = AssessmentRun.objects.prefetch_related("releases").get(pk=run_id)
        except AssessmentRun.DoesNotExist:
            logger.debug("[DT] sync_release_tags: run %s no longer exists, skipping", run_id)
            return

        # Canonical full release name set from the M2M (Q2=B).
        # Note: if the same release name exists across multiple products
        # (e.g. both Product A and Product B have "v1.0.0"), they collapse
        # into one tag. This is intentional — DT tags are flat strings and
        # the DT project represents the component's risk regardless of which
        # product embeds it.
        canonical_names = sorted({r.name for r in run.releases.all()})

        # Find the DT version row. There may be multiple dt_servers per
        # (sbom, ...), so update all.
        version_rows = list(
            SbomDependencyTrackProjectVersion.objects.filter(sbom_id=sbom_id).select_related("dt_server")
        )
        if not version_rows:
            logger.debug(
                "[DT] sync_release_tags: no DT project version row for SBOM %s, nothing to sync",
                sbom_id,
            )
            return

        for version_row in version_rows:
            try:
                client = DependencyTrackClient(version_row.dt_server.url, version_row.dt_server.api_key)
                client.set_project_tags(str(version_row.dt_project_version_uuid), canonical_names)
                logger.info(
                    "[DT] sync_release_tags: set tags=%s on version %s for SBOM %s",
                    canonical_names,
                    version_row.dt_project_version_uuid,
                    sbom_id,
                )
            except Exception:
                logger.warning(
                    "[DT] sync_release_tags: failed to set tags on version %s for SBOM %s",
                    version_row.dt_project_version_uuid,
                    sbom_id,
                    exc_info=True,
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
            is_cyclonedx: bool = content.get("bomFormat") == "CycloneDX"
            return is_cyclonedx
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False

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
        from sbomify.apps.vulnerability_scanning.models import DependencyTrackServer
        from sbomify.apps.vulnerability_scanning.services import VulnerabilityScanningService

        dt_server_id = self.config.get("dt_server_id")
        if dt_server_id:
            try:
                return DependencyTrackServer.objects.get(id=dt_server_id, is_active=True)
            except DependencyTrackServer.DoesNotExist:
                logger.warning(f"[DT] Configured server {dt_server_id} not found/inactive, falling back to pool")

        service = VulnerabilityScanningService()
        return service.select_dependency_track_server(team)

    def _compute_project_name(self, sbom: Any) -> str:
        """Compute the canonical DT project name for a component.

        Uses the component's unique 12-char alphanumeric token (``component.id``,
        generated by ``generate_id()`` — not a UUID, not user-supplied) to
        avoid cross-team collisions on shared DT server pools. Two teams
        with a component named "api" get different DT projects because their
        component IDs differ.

        Design stance: one DT project per (env, component) — product is
        intentionally NOT part of the name. Multi-product components get a
        single DT project with tags from all products' releases. Teams
        maintaining v1/v2 as separate Products will see unified vuln counts
        with tag filtering as the only separator. This matches DT's "one
        project per logical component" guidance (issue #695).
        """
        from sbomify.apps.vulnerability_scanning.services import VulnerabilityScanningService

        env_prefix = VulnerabilityScanningService()._get_environment_prefix()
        component_id = sbom.component.id if sbom.component else "unknown"
        return f"{env_prefix}-sbomify-{component_id}"

    def _poll_results(
        self,
        *,
        client: Any,
        version_row: Any,
        sbom_id: str,
        project_name: str,
        current_release_names: list[str],
    ) -> AssessmentResult:
        """Poll DT for vulnerability results using the stored per-SBOM version UUID.

        Called on retry after the first upload raised ``RetryLaterError``. Uses
        the ``dt_project_version_uuid`` stored on the
        ``SbomDependencyTrackProjectVersion`` row — no need to re-lookup by
        (name, version) since we persisted the UUID at upload time.

        Args:
            client: DependencyTrackClient instance for the selected server.
            version_row: SbomDependencyTrackProjectVersion row for (sbom, dt_server).
            sbom_id: SBOM primary key for logging.
            project_name: Canonical DT project name (for result metadata).
            current_release_names: Current release tag set (for result metadata).

        Returns:
            AssessmentResult with findings for this SBOM's DT project version.

        Raises:
            RetryLaterError: If DT is still processing.
        """
        version_uuid = str(version_row.dt_project_version_uuid)

        try:
            metrics = client.get_project_metrics(version_uuid)
        except Exception:
            raise RetryLaterError("Dependency Track project metrics not yet available")

        if not metrics:
            raise RetryLaterError("Dependency Track still processing SBOM")

        vulnerabilities_response = client.get_project_vulnerabilities(version_uuid)
        vulnerabilities = vulnerabilities_response.get("content", [])

        # Opt-in: pull DT's triage decisions back as a VEX so analysts'
        # judgments made in DT reach sbomify without a manual export/upload.
        # Off by default — the hosted DT is a scanner backend, not a VEX
        # source. Best-effort when on: a failure must never fail the scan.
        self._sync_triage_vex_safely(client, version_row)

        now = dj_timezone.now()
        version_row.last_metrics_sync = now
        version_row.save(update_fields=["last_metrics_sync", "updated_at"])

        # Also update the component-level mapping so admin/API consumers see
        # the most recent poll timestamp at the component level (not just per-SBOM).
        from sbomify.apps.vulnerability_scanning.models import ComponentDependencyTrackMapping

        ComponentDependencyTrackMapping.objects.filter(
            component=version_row.sbom.component,
            dt_server=version_row.dt_server,
        ).update(last_metrics_sync=now)

        findings = self._convert_dt_findings(vulnerabilities)

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
                "dt_project_release_tags": sorted(set(current_release_names)),
                "metrics": metrics,
            },
        )

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
        artifact on the component (as received, per ADR-004). Content is
        deduplicated against the component's newest VEX ignoring the volatile
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

        from sbomify.apps.core.object_store import S3Client
        from sbomify.apps.sboms.models import SBOM as SBOMModel
        from sbomify.apps.sboms.services.sboms import schedule_vex_reapply

        component = version_row.sbom.component
        normalized = self._normalized_vex(doc)
        s3 = S3Client("SBOMS")

        newest = (
            SBOMModel.objects.filter(component=component, bom_type=SBOMModel.BomType.VEX.value)
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
        filename = s3.upload_sbom(raw)
        metadata_component = (doc.get("metadata") or {}).get("component") or {}
        vex = SBOMModel.objects.create(
            component=component,
            bom_type=SBOMModel.BomType.VEX.value,
            name=metadata_component.get("name") or f"{component.name}-vex",
            version=dj_timezone.now().strftime("dt-triage-%Y%m%d%H%M%S"),
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
                    },
                    cvss_score=cvss_score,
                    references=references,
                    aliases=aliases,
                )
            )

        return findings

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

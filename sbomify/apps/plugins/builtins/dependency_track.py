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


class DependencyTrackPlugin(AssessmentPlugin):
    """Dependency Track vulnerability scanning plugin.

    Scans CycloneDX SBOMs by uploading them to a Dependency Track server
    and polling for vulnerability results. SPDX SBOMs are rejected since
    DT only supports CycloneDX.

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

        # Validate CycloneDX format (DT does not support SPDX)
        if not self._validate_cyclonedx(sbom_bytes):
            return self._create_error_result(
                "Dependency Track only supports CycloneDX format. "
                "This SBOM appears to be SPDX or an unrecognized format."
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

        # Guard: DT scanning requires product membership. Check via the
        # Project→Product link (stable at SBOM creation time) rather than
        # ReleaseArtifact (subject to race — sbomify-action creates the SBOM
        # and release association in separate API calls, so the ReleaseArtifact
        # may not exist yet when the upload-triggered scan fires).
        from sbomify.apps.core.models import Project

        has_product = Project.objects.filter(
            components=sbom.component,
            products__isnull=False,
        ).exists()
        if not has_product:
            return self._create_skipped_result(
                finding_id="dependency-track:no-product",
                title="Skipped — component has no product membership",
                description=(
                    "Dependency Track scanning requires the component to be linked "
                    "to a product (via a project). This component has no product "
                    "membership, so no release context exists for DT tags."
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

            # Extract CVSS score
            cvss_score = vuln_data.get("cvssV3BaseScore") or vuln_data.get("cvssV2BaseScore")
            if cvss_score is not None:
                try:
                    cvss_score = float(cvss_score)
                except (ValueError, TypeError):
                    cvss_score = None

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

            aliases = vuln_data.get("aliases", []) or None

            findings.append(
                Finding(
                    id=vuln_id,
                    title=vuln_data.get("title", vuln_data.get("description", ""))[:200]
                    if vuln_data.get("title") or vuln_data.get("description")
                    else "No description",
                    description=vuln_data.get("description", ""),
                    severity=severity,
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

    def _build_single_finding_result(
        self,
        *,
        finding_id: str,
        title: str,
        description: str,
        status: str,
        severity: str,
        metadata: dict[str, Any],
        pass_count: int = 0,
        fail_count: int = 0,
        warning_count: int = 0,
        error_count: int = 0,
    ) -> AssessmentResult:
        """Construct an AssessmentResult with a single Finding.

        Used by both _create_error_result (for operational failures) and
        _create_skipped_result (for "plugin preconditions not met" cases).
        Keeps the plugin_name, version, category, and timestamp construction
        in one place so future changes don't need to be duplicated across
        result helpers.
        """
        finding = Finding(
            id=finding_id,
            title=title,
            description=description,
            status=status,
            severity=severity,
        )
        summary = AssessmentSummary(
            total_findings=1,
            pass_count=pass_count,
            fail_count=fail_count,
            warning_count=warning_count,
            error_count=error_count,
        )
        return AssessmentResult(
            plugin_name="dependency-track",
            plugin_version=self.VERSION,
            category=AssessmentCategory.SECURITY.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=[finding],
            metadata=metadata,
        )

    def _create_error_result(self, error_message: str) -> AssessmentResult:
        """Create an error result when assessment cannot be completed.

        Args:
            error_message: Description of the error.

        Returns:
            AssessmentResult with a single error finding.
        """
        return self._build_single_finding_result(
            finding_id="dependency-track:error",
            title="Scan Error",
            description=error_message,
            status="error",
            severity="high",
            metadata={"error": True},
            error_count=1,
        )

    def _create_skipped_result(
        self,
        finding_id: str,
        title: str,
        description: str,
    ) -> AssessmentResult:
        """Create a non-failing result indicating the assessment was skipped.

        Used when the plugin's preconditions aren't met but the situation is
        not an error. Currently used when an SBOM has no release association
        (e.g., a cron-triggered scan picks up an SBOM that was never linked
        to a release).

        The returned finding uses status="warning" with severity="info", and
        the top-level AssessmentResult metadata contains {"skipped": True}.
        API consumers that aggregate plugin results into an overall posture
        MUST check metadata["skipped"] to distinguish "assessment was skipped"
        from "assessment ran and reported a real warning finding". A raw
        status check alone is not sufficient.

        Args:
            finding_id: Stable identifier for the finding.
            title: Human-readable title.
            description: Detailed reason the assessment was skipped.

        Returns:
            AssessmentResult with a single warning finding and
            metadata={"skipped": True}.
        """
        return self._build_single_finding_result(
            finding_id=finding_id,
            title=title,
            description=description,
            status="warning",
            severity="info",
            metadata={"skipped": True},
            warning_count=1,
        )

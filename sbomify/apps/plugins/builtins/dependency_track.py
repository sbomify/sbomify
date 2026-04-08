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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from django.db import IntegrityError
from django.utils import timezone as dj_timezone

from sbomify.apps.plugins.sdk.base import AssessmentPlugin, RetryLaterError, SBOMContext
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
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

        # Resolve the release this scan targets.
        #
        # Preferred path: the trigger (signal handler or per-release cron)
        # threaded a specific release_id through SBOMContext. That ID points
        # to the exact release association that caused this run — use it.
        # This is the only correct choice when an SBOM is linked to multiple
        # releases (e.g., same SBOM in both v1 and v1.1 of a product): each
        # release has its own DT project and must be scanned independently.
        #
        # Fallback: legacy callers that don't propagate a release context
        # (e.g., manual API triggers) fall back to _find_release_for_sbom
        # which picks the newest non-"latest" release. That heuristic is
        # necessarily imperfect when multiple releases exist, but it is
        # preserved for backward compatibility.
        release = None
        if context is not None and context.release_id:
            from sbomify.apps.core.models import Release

            try:
                release = Release.objects.select_related("product").get(pk=context.release_id)
            except Release.DoesNotExist:
                # TOCTOU: the Release was deleted between trigger fire and task
                # execution. Skip rather than fall back — the fallback would
                # silently scan a different release than the one that actually
                # triggered this run, which is worse than skipping.
                logger.warning(
                    "[DT] SBOMContext.release_id=%s was deleted between trigger and execution; skipping scan",
                    context.release_id,
                )
                return self._create_skipped_result(
                    finding_id="dependency-track:release-deleted",
                    title="Skipped — triggering release was deleted",
                    description=(
                        "The release that triggered this Dependency Track scan was deleted "
                        "before the scan could run. This is expected if the release was "
                        "removed shortly after it was created. The SBOM itself is unaffected."
                    ),
                )

            # Defense-in-depth: the signal handler and the cron path both
            # filter by team ownership, but a cross-team release reference
            # could still arrive via admin/migration paths. If the Release
            # belongs to a different team than the SBOM, refuse the scan
            # rather than invoke DT under the wrong team's credentials.
            if release.product.team_id != team.id:
                logger.warning(
                    "[DT] SBOMContext.release_id=%s belongs to team %s but SBOM %s belongs to team %s; "
                    "refusing cross-team scan",
                    context.release_id,
                    release.product.team_id,
                    sbom_id,
                    team.id,
                )
                return self._create_error_result("Cross-team release reference detected; scan aborted")

        if release is None:
            release = self._find_release_for_sbom(sbom_id, team_id=team.id)
        if not release:
            return self._create_skipped_result(
                finding_id="dependency-track:no-release",
                title="Skipped — SBOM has no release association",
                description=(
                    "Dependency Track only scans SBOMs that are part of a release. "
                    "This SBOM is not currently linked to any release via "
                    "ReleaseArtifact, so it was skipped."
                ),
            )

        # Resolve the DT server and existing mapping.
        # The mapping is now keyed on (component, dt_server) — one DT project
        # per component, with multiple release versions inside.
        from sbomify.apps.vulnerability_scanning.models import ComponentDependencyTrackMapping

        existing_mapping = ComponentDependencyTrackMapping.objects.filter(component=sbom.component).first()  # type: ignore[misc]
        if existing_mapping:
            dt_server = existing_mapping.dt_server
        else:
            try:
                dt_server = self._select_dt_server(team)
            except RuntimeError as e:
                return self._create_error_result(str(e))

        try:
            mapping, just_uploaded = self._get_or_create_mapping_and_upload(
                release, sbom, sbom_bytes, dt_server, existing_mapping
            )
        except Exception as e:
            logger.error(f"[DT] Failed to get/create mapping for SBOM {sbom_id}: {e}")
            return self._create_error_result(f"DT project setup failed: {e}")

        if mapping is None:
            return self._create_error_result("Could not find DT project after SBOM upload")

        if just_uploaded:
            logger.info(f"[DT] SBOM {sbom_id} uploaded to DT, will poll for results")
            raise RetryLaterError("SBOM uploaded to Dependency Track, waiting for vulnerability analysis")

        try:
            return self._poll_results(mapping, sbom_id)
        except RetryLaterError:
            raise
        except Exception as e:
            logger.error(f"[DT] Failed to poll results for SBOM {sbom_id}: {e}")
            return self._create_error_result(f"Failed to poll DT results: {e}")

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

    def _find_release_for_sbom(self, sbom_id: str, team_id: Any = None) -> Any:
        """Find the release associated with this SBOM via ReleaseArtifact.

        When an SBOM is linked to multiple releases (e.g., the auto-maintained
        "latest" release plus one or more named releases), this method prefers
        the newest non-"latest" release. The "latest" release is a rolling
        pointer maintained by update_latest_release_on_sbom_created; DT should
        always operate against explicit named releases where available so that
        DT projects are tied to point-in-time releases, not a moving target.

        If no non-"latest" release exists (e.g., the SBOM was uploaded but
        never associated with a named release), this method falls back to any
        available release so cron / manual triggers still have something to
        work with.

        Args:
            sbom_id: SBOM primary key.
            team_id: When provided, restricts the lookup to releases whose
                product belongs to this team. This is defense-in-depth against
                cross-team ReleaseArtifact rows (normally prevented by
                add_artifact_to_release's team check, but admin/migration
                paths can bypass it). Callers that have the team context
                should always pass it.

        Returns:
            Release instance or None.
        """
        from sbomify.apps.core.models import ReleaseArtifact

        base_filter: dict[str, Any] = {"sbom_id": sbom_id}
        if team_id is not None:
            base_filter["release__product__team_id"] = team_id

        # Prefer the newest non-"latest" ReleaseArtifact for determinism
        artifact = (
            ReleaseArtifact.objects.filter(**base_filter)
            .exclude(release__is_latest=True)
            .select_related("release__product")
            .order_by("-created_at", "-id")
            .first()
        )
        if artifact is None:
            # Fallback: SBOMs that only exist in the "latest" rolling release.
            # Cron / manual triggers may still want to scan them.
            artifact = (
                ReleaseArtifact.objects.filter(**base_filter)
                .select_related("release__product")
                .order_by("-created_at", "-id")
                .first()
            )
        if artifact:
            return artifact.release
        return None

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

    def _get_or_create_mapping_and_upload(
        self, release: Any, sbom: Any, sbom_bytes: bytes, dt_server: Any, existing_mapping: Any
    ) -> tuple[Any, bool]:
        """Upload SBOM and create/update mapping. Server selection is done by caller.

        Args:
            release: Release instance — its name becomes the DT project version.
            sbom: SBOM model instance — used to access sbom.component.
            sbom_bytes: Raw SBOM content.
            dt_server: Pre-selected DependencyTrackServer (caller owns the reference).
            existing_mapping: Pre-fetched ComponentDependencyTrackMapping or None.

        Returns:
            Tuple of (mapping, just_uploaded).
        """
        from sbomify.apps.vulnerability_scanning.clients import (
            DependencyTrackClient,
        )
        from sbomify.apps.vulnerability_scanning.models import (
            ComponentDependencyTrackMapping,
        )
        from sbomify.apps.vulnerability_scanning.services import (
            VulnerabilityScanningService,
        )

        service = VulnerabilityScanningService()

        if existing_mapping:
            stale_threshold = dj_timezone.now() - timedelta(hours=24)
            if existing_mapping.last_sbom_upload and existing_mapping.last_sbom_upload > stale_threshold:
                return existing_mapping, False

            # Re-upload to the existing DT project using the release name as version.
            # The project already exists in DT; we just push a new version of the BOM.
            client = DependencyTrackClient(dt_server.url, dt_server.api_key)
            project_version = release.name
            client.upload_sbom_with_project_creation(
                project_name=existing_mapping.dt_project_name,
                project_version=project_version,
                sbom_data=sbom_bytes,
                auto_create=True,
            )
            existing_mapping.last_sbom_upload = dj_timezone.now()
            existing_mapping.save(update_fields=["last_sbom_upload", "updated_at"])
            return existing_mapping, True

        # No existing mapping — create DT project and mapping.
        #
        # DT-canonical pattern: one DT project per logical component, with multiple
        # versions inside — one per release. This matches the DT "Best Practices"
        # documentation and the community consensus from DT issue #695 ("How to use
        # projects and versions") and the DT mailing list "One or multiple projects?"
        # thread. Using one project per component (not one per release) keeps the DT
        # project list manageable and lets DT's native UI compare scan results across
        # release versions within a single project tree.
        #
        # Category A customers (continuous deployment / TrunkVer, no named releases):
        #   - PRODUCT_RELEASE env var is not set; the auto-'latest' release is the
        #     only one. They see ONE DT project per component with ONE version
        #     ('latest') that updates continuously. Same experience as the pre-PR
        #     rolling-project model.
        #
        # Category B customers (LTS branches, CalVer, FDA medical device, EU CRA):
        #   - PRODUCT_RELEASE is set to a tag (e.g., 'v1.0.0'). They see ONE DT
        #     project per component with multiple versions inside ('latest',
        #     'v1.0.0', 'v1.1.0', ...), each independently scanned. EU CRA 5-year
        #     monitoring and FDA per-version lifecycle tracking both work because
        #     each version has its own scan history in DT (and its own AssessmentRun
        #     history on the sbomify side via the AssessmentRun.release FK).
        client = DependencyTrackClient(dt_server.url, dt_server.api_key)
        env_prefix = service._get_environment_prefix()

        product_name = release.product.name if release.product else "unknown"
        safe_product_name = product_name.replace("/", "-").replace(" ", "-").lower()
        component_name = sbom.component.name if sbom.component else "unknown"
        safe_component_name = component_name.replace("/", "-").replace(" ", "-").lower()
        project_name = f"{env_prefix}-sbomify-{safe_product_name}-{safe_component_name}"
        project_version = release.name

        client.upload_sbom_with_project_creation(
            project_name=project_name,
            project_version=project_version,
            sbom_data=sbom_bytes,
            auto_create=True,
        )

        project_data = client.find_project_by_name_version(project_name, project_version)
        if not project_data:
            logger.error(f"[DT] Could not find project {project_name} v{project_version} after upload")
            return None, False

        try:
            mapping, created = ComponentDependencyTrackMapping.objects.get_or_create(
                component=sbom.component,
                dt_server=dt_server,
                defaults={
                    "dt_project_uuid": project_data["uuid"],
                    "dt_project_name": project_name,
                    "last_sbom_upload": dj_timezone.now(),
                },
            )
        except IntegrityError:
            mapping = ComponentDependencyTrackMapping.objects.get(component=sbom.component, dt_server=dt_server)
            created = False

        if created:
            logger.info(f"[DT] Created mapping for component {sbom.component.id} -> DT project {project_name}")
        else:
            logger.info(f"[DT] Reused existing mapping for component {sbom.component.id}")

        return mapping, True

    def _poll_results(self, mapping: Any, sbom_id: str) -> AssessmentResult:
        """Poll DT for vulnerability results.

        Args:
            mapping: ReleaseDependencyTrackMapping instance.
            sbom_id: SBOM primary key for logging.

        Returns:
            AssessmentResult with findings.

        Raises:
            RetryLaterError: If DT is still processing.
        """
        from sbomify.apps.vulnerability_scanning.clients import DependencyTrackClient

        client = DependencyTrackClient(mapping.dt_server.url, mapping.dt_server.api_key)

        # Get project metrics to check if processing is complete
        try:
            metrics = client.get_project_metrics(str(mapping.dt_project_uuid))
        except Exception:
            raise RetryLaterError("Dependency Track project metrics not yet available")

        if not metrics:
            raise RetryLaterError("Dependency Track still processing SBOM")

        # Get vulnerability findings
        vulnerabilities_response = client.get_project_vulnerabilities(str(mapping.dt_project_uuid))
        vulnerabilities = vulnerabilities_response.get("content", [])

        # Update sync timestamp
        mapping.last_metrics_sync = dj_timezone.now()
        mapping.save(update_fields=["last_metrics_sync", "updated_at"])

        # Convert DT findings to plugin Finding objects
        findings = self._convert_dt_findings(vulnerabilities)

        # Build severity summary
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
                "dt_server": str(mapping.dt_server.id),
                "dt_project_uuid": str(mapping.dt_project_uuid),
                "dt_project_name": mapping.dt_project_name,
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

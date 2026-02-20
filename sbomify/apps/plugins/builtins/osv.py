"""OSV vulnerability scanning plugin.

This plugin wraps the OSV scanner binary to scan SBOMs for known
vulnerabilities using the OSV (Open Source Vulnerabilities) database.

It supports both CycloneDX and SPDX SBOM formats. The scanner binary
requires files with the correct suffix (.cdx.json or .spdx.json) for
format detection, so the plugin creates a correctly-suffixed temporary
copy when needed.

Reference:
    - OSV: https://osv.dev/
    - osv-scanner: https://github.com/google/osv-scanner
"""

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sbomify.apps.plugins.sdk.base import AssessmentPlugin
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.plugins.sdk.results import (
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
)
from sbomify.logging import getLogger

logger = getLogger(__name__)


class OSVPlugin(AssessmentPlugin):
    """OSV vulnerability scanning plugin.

    Scans SBOMs for known vulnerabilities using the osv-scanner binary.
    Supports both CycloneDX and SPDX formats.

    Attributes:
        VERSION: Plugin version (semantic versioning).
        DEFAULT_TIMEOUT: Default scanner timeout in seconds.
        DEFAULT_SCANNER_PATH: Default path to osv-scanner binary.

    Config options:
        timeout: Scanner timeout in seconds (default: DEFAULT_TIMEOUT).
        scanner_path: Path to osv-scanner binary (default: DEFAULT_SCANNER_PATH).
    """

    VERSION = "1.0.0"
    DEFAULT_TIMEOUT = 300
    DEFAULT_SCANNER_PATH = "/usr/local/bin/osv-scanner"

    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        return PluginMetadata(
            name="osv",
            version=self.VERSION,
            category=AssessmentCategory.SECURITY,
        )

    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict | None = None,
    ) -> AssessmentResult:
        """Scan SBOM for vulnerabilities using osv-scanner.

        The orchestrator provides files with a generic .json suffix, but
        osv-scanner requires .cdx.json or .spdx.json for format detection.
        This method creates a correctly-suffixed copy in the same temp
        directory and cleans it up after scanning.

        Args:
            sbom_id: The SBOM's primary key (for logging/reference).
            sbom_path: Path to the SBOM file on disk.
            dependency_status: Not used by this plugin.

        Returns:
            AssessmentResult with vulnerability findings.
        """
        logger.info(f"[OSV] Starting vulnerability scan for SBOM {sbom_id}")

        timeout = self.config.get("timeout", self.DEFAULT_TIMEOUT)
        scanner_path = self.config.get("scanner_path", self.DEFAULT_SCANNER_PATH)

        # Read SBOM content for format detection
        try:
            sbom_bytes = sbom_path.read_bytes()
        except Exception as e:
            logger.error(f"[OSV] Failed to read SBOM file: {e}")
            return self._create_error_result(f"Failed to read SBOM: {e}")

        # Check for unsupported SPDX 3.0 format
        if self._is_spdx3(sbom_bytes):
            logger.warning(f"[OSV] SPDX 3.0 format not supported by osv-scanner for SBOM {sbom_id}")
            return self._create_unsupported_format_result()

        # Determine correct file suffix and create temp copy if needed
        suffix = self._determine_file_suffix(sbom_bytes)
        scan_path = sbom_path
        temp_copy: Path | None = None

        if not str(sbom_path).endswith(suffix):
            temp_copy = sbom_path.parent / f"{sbom_path.stem}{suffix}"
            shutil.copy2(sbom_path, temp_copy)
            scan_path = temp_copy
            logger.debug(f"[OSV] Created temp copy with suffix {suffix}: {temp_copy}")

        try:
            # Execute osv-scanner
            stdout, stderr, returncode = self._execute_scanner(scanner_path, scan_path, timeout)

            # Parse results into findings
            findings = self._parse_scan_output(stdout, returncode)

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

            logger.info(f"[OSV] Completed scan for SBOM {sbom_id}: {len(findings)} vulnerabilities found")

            return AssessmentResult(
                plugin_name="osv",
                plugin_version=self.VERSION,
                category=AssessmentCategory.SECURITY.value,
                assessed_at=datetime.now(timezone.utc).isoformat(),
                summary=summary,
                findings=findings,
                metadata={
                    "scanner": "osv-scanner",
                    "sbom_format": self._detect_format_name(sbom_bytes),
                },
            )

        except subprocess.TimeoutExpired:
            logger.error(f"[OSV] Scanner timed out after {timeout}s for SBOM {sbom_id}")
            return self._create_error_result(f"OSV scanner timed out after {timeout} seconds")

        except FileNotFoundError:
            logger.error(f"[OSV] Scanner binary not found: {scanner_path}")
            return self._create_error_result(f"OSV scanner binary not found: {scanner_path}")

        finally:
            # Clean up temp copy
            if temp_copy and temp_copy.exists():
                temp_copy.unlink()
                logger.debug(f"[OSV] Cleaned up temp copy: {temp_copy}")

    def _determine_file_suffix(self, sbom_data: bytes) -> str:
        """Determine file suffix from SBOM content for osv-scanner format detection.

        Args:
            sbom_data: Raw SBOM bytes.

        Returns:
            File suffix string: ".cdx.json", ".spdx.json", or ".json".
        """
        try:
            content = json.loads(sbom_data.decode("utf-8"))
            if content.get("bomFormat") == "CycloneDX":
                return ".cdx.json"
            elif content.get("spdxVersion"):
                return ".spdx.json"
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        return ".json"

    def _detect_format_name(self, sbom_data: bytes) -> str:
        """Detect SBOM format name from content.

        Args:
            sbom_data: Raw SBOM bytes.

        Returns:
            Format string: "cyclonedx", "spdx", or "unknown".
        """
        try:
            content = json.loads(sbom_data.decode("utf-8"))
            if content.get("bomFormat") == "CycloneDX":
                return "cyclonedx"
            elif content.get("spdxVersion"):
                return "spdx"
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        return "unknown"

    @staticmethod
    def _is_spdx3(sbom_data: bytes) -> bool:
        """Check if raw SBOM data is SPDX 3.x format.

        Detection criteria:
            - @context contains "spdx.org/rdf/3.0" (string, list, or dict), or
            - root-level spdxVersion starts with "SPDX-3.".
        """
        try:
            content = json.loads(sbom_data.decode("utf-8"))
            context = content.get("@context")
            if context is not None and "spdx.org/rdf/3.0" in str(context):
                return True

            spdx_version = content.get("spdxVersion")
            if isinstance(spdx_version, str) and spdx_version.startswith("SPDX-3."):
                return True
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        return False

    def _create_unsupported_format_result(self) -> AssessmentResult:
        """Create a result indicating SPDX 3.0 is not yet supported by osv-scanner."""
        finding = Finding(
            id="osv:unsupported-format",
            title="SPDX 3.0 Not Supported",
            description=(
                "osv-scanner does not yet support SPDX 3.0 format. "
                "Vulnerability scanning requires SPDX 2.x or CycloneDX format. "
                "See https://github.com/google/osv-scanner for format support updates."
            ),
            status="warning",
            severity="info",
        )

        summary = AssessmentSummary(
            total_findings=1,
            pass_count=0,
            fail_count=0,
            error_count=0,
            warning_count=1,
        )

        return AssessmentResult(
            plugin_name="osv",
            plugin_version=self.VERSION,
            category=AssessmentCategory.SECURITY.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=[finding],
            metadata={
                "scanner": "osv-scanner",
                "sbom_format": "spdx3",
                "unsupported_format": True,
            },
        )

    def _execute_scanner(
        self,
        scanner_path: str,
        sbom_path: Path,
        timeout: int,
    ) -> tuple[str, str, int]:
        """Execute osv-scanner binary.

        Args:
            scanner_path: Path to the osv-scanner binary.
            sbom_path: Path to the SBOM file.
            timeout: Timeout in seconds.

        Returns:
            Tuple of (stdout, stderr, returncode).

        Raises:
            subprocess.TimeoutExpired: If scanner exceeds timeout.
            FileNotFoundError: If scanner binary not found.
        """
        absolute_path = sbom_path.resolve()
        scan_command = [
            scanner_path,
            "scan",
            "source",
            "--sbom",
            str(absolute_path),
            "--format",
            "json",
        ]

        logger.debug(f"[OSV] Executing: {' '.join(scan_command)}")

        # Use a minimal environment to avoid leaking unrelated secrets to the scanner.
        # Preserve a controlled PATH and selectively propagate proxy/TLS-related variables
        # that osv-scanner may rely on.
        scanner_env: dict[str, str] = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        }
        for var_name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "HOME",
        ):
            if var_name in os.environ:
                scanner_env[var_name] = os.environ[var_name]

        process = subprocess.run(
            scan_command,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            env=scanner_env,
            cwd=str(absolute_path.parent),
        )

        # Exit code 0 = no vulns, 1 = vulns found, other = error
        if process.returncode not in (0, 1):
            logger.warning(f"[OSV] Scanner returned code {process.returncode}: {process.stderr}")

        return process.stdout, process.stderr, process.returncode

    def _parse_scan_output(self, stdout: str, returncode: int) -> list[Finding]:
        """Parse osv-scanner JSON output into Finding objects.

        Args:
            stdout: Scanner stdout (JSON).
            returncode: Scanner exit code.

        Returns:
            List of Finding objects.
        """
        if not stdout or returncode == 0:
            return []

        try:
            raw_results = json.loads(stdout)
        except json.JSONDecodeError as e:
            logger.error(f"[OSV] Failed to parse scanner output: {e}")
            return []

        findings: list[Finding] = []

        for result in raw_results.get("results", []):
            for package in result.get("packages", []):
                pkg_info = package.get("package", {})
                component = {
                    "name": pkg_info.get("name"),
                    "version": pkg_info.get("version"),
                    "ecosystem": pkg_info.get("ecosystem"),
                }

                for vuln in package.get("vulnerabilities", []):
                    severity, cvss_score = self._map_severity(vuln)
                    references = [ref.get("url") for ref in vuln.get("references", []) if ref.get("url")]
                    aliases = vuln.get("aliases", [])

                    # Extract timestamps
                    published_at = vuln.get("published")
                    modified_at = vuln.get("modified")

                    findings.append(
                        Finding(
                            id=vuln.get("id", "unknown"),
                            title=vuln.get("summary", vuln.get("id", "Unknown vulnerability")),
                            description=vuln.get("details", ""),
                            severity=severity,
                            component=component,
                            cvss_score=cvss_score,
                            references=references or None,
                            aliases=aliases or None,
                            published_at=published_at,
                            modified_at=modified_at,
                        )
                    )

        return findings

    def _map_severity(self, vuln: dict[str, Any]) -> tuple[str, float | None]:
        """Map OSV vulnerability data to severity level and CVSS score.

        Checks multiple sources in order:
        1. CVSS v3 vector in severity field
        2. Explicit severity in database_specific
        3. CVSS numeric scores in database_specific

        Args:
            vuln: OSV vulnerability dict.

        Returns:
            Tuple of (severity_string, cvss_score_or_none).
        """
        cvss_score: float | None = None

        # 1. Check CVSS v3 severity field
        for severity_item in vuln.get("severity", []):
            if severity_item.get("type") == "CVSS_V3":
                cvss_string = severity_item.get("score", "")
                score = self._extract_cvss_score(cvss_string)
                if score is not None:
                    cvss_score = score
                    return self._score_to_severity(score), cvss_score

        # 2. Check database_specific severity in affected ranges
        for affected in vuln.get("affected", []):
            for range_item in affected.get("ranges", []):
                db_specific = range_item.get("database_specific", {})
                if "severity" in db_specific:
                    sev = db_specific["severity"]
                    if isinstance(sev, list) and sev:
                        return sev[0].lower(), cvss_score
                    elif isinstance(sev, str):
                        return sev.lower(), cvss_score

        # 3. Check CVSS scores in database_specific
        best_score: float | None = None
        for affected in vuln.get("affected", []):
            for range_item in affected.get("ranges", []):
                db_specific = range_item.get("database_specific", {})
                raw_score = db_specific.get("cvss_score") or db_specific.get("cvss_v3_score")
                if raw_score:
                    try:
                        score = float(raw_score)
                        if best_score is None or score > best_score:
                            best_score = score
                    except (ValueError, TypeError):
                        pass

        if best_score is not None:
            return self._score_to_severity(best_score), best_score

        # Default
        return "medium", None

    def _extract_cvss_score(self, cvss_string: str) -> float | None:
        """Extract numeric CVSS score from a CVSS v3 vector string.

        Uses a regex to find the base score at the end of the vector.
        If that fails, uses simple heuristics on the vector components.

        Note: The heuristic fallback produces approximate scores based on
        impact metrics only (C/I/A and Scope). It does not account for
        exploitability metrics (AV, AC, PR, UI), so scores may differ from
        a full CVSS calculation. This is acceptable because most OSV entries
        include a proper numeric score; the heuristic is a last resort.

        Args:
            cvss_string: CVSS v3 vector string (e.g., "CVSS:3.1/AV:N/...").

        Returns:
            Numeric CVSS score or None if the vector cannot be parsed.
        """
        if not cvss_string or not cvss_string.startswith("CVSS:3"):
            return None

        # Try to extract trailing numeric score (some formats append it)
        score_match = re.search(r"/(\d+\.?\d*)$", cvss_string)
        if score_match:
            try:
                return float(score_match.group(1))
            except ValueError:
                pass

        # Heuristic scoring based on vector components
        if "C:H/I:H/A:H" in cvss_string and "S:C" in cvss_string:
            return 10.0
        elif "C:H/I:H/A:H" in cvss_string:
            return 9.0
        elif any(f"{m}:H" in cvss_string for m in ("C", "I", "A")):
            return 7.5
        elif any(f"{m}:L" in cvss_string for m in ("C", "I", "A")):
            return 4.0

        return None

    @staticmethod
    def _score_to_severity(score: float) -> str:
        """Convert numeric CVSS score to severity level.

        Args:
            score: CVSS numeric score (0-10).

        Returns:
            Severity string: "critical", "high", "medium", or "low".
        """
        if score >= 9.0:
            return "critical"
        elif score >= 7.0:
            return "high"
        elif score >= 4.0:
            return "medium"
        return "low"

    def _create_error_result(self, error_message: str) -> AssessmentResult:
        """Create an error result when assessment cannot be completed.

        Args:
            error_message: Description of the error.

        Returns:
            AssessmentResult with error finding.
        """
        finding = Finding(
            id="osv:error",
            title="Scan Error",
            description=error_message,
            status="error",
            severity="high",
        )

        summary = AssessmentSummary(
            total_findings=1,
            pass_count=0,
            fail_count=0,
            warning_count=0,
            error_count=1,
        )

        return AssessmentResult(
            plugin_name="osv",
            plugin_version=self.VERSION,
            category=AssessmentCategory.SECURITY.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=[finding],
            metadata={"error": True},
        )

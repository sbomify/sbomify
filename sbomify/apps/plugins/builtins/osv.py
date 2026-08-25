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

from sbomify.apps.plugins.sdk.base import AssessmentPlugin, SBOMContext
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.plugins.sdk.results import (
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
)
from sbomify.logging import getLogger

logger = getLogger(__name__)

# Ceiling on how much captured stderr reaches a log line. Generous enough that
# a real scanner failure fits whole, bounded so a scanner looping on per-package
# warnings cannot emit a megabyte-wide record.
_STDERR_LOG_LIMIT = 2000

# How much of that budget the head keeps when the output is longer. A panic
# message, a usage error and an early TLS failure all announce themselves in
# the first line or two; the tail gets the rest because a scanner that dies
# part way through has usually said why just before it stopped.
_STDERR_HEAD_CHARS = 600


def _collapse_for_log(text: str) -> str:
    """Fold multi-line captured output into a single log-safe line.

    The log pipeline splits records on newlines, so a multi-line stderr arrives
    as one line per line and only the first survives as part of the message
    that names it. osv-scanner opens with a progress line, which is how a
    failed scan came through staging as

        [OSV] Scanner returned code 127: Starting filesystem walk for root: /

    — the exit code preserved and the reason for it discarded.

    Truncation keeps both ends. Keeping only the tail was the first attempt,
    on the reasoning that a scanner says why it died in its last few lines —
    true for a lockfile or network error, false for the case that matters most:
    a Go panic puts its message on line one and then ten kilobytes of goroutine
    stack after it, so a tail-only cut discarded the cause and kept the frames.
    Since this helper is the only route stderr takes to the logs, whatever it
    drops is not written anywhere.
    """
    joined = " | ".join(line.strip() for line in (text or "").splitlines() if line.strip())
    if len(joined) <= _STDERR_LOG_LIMIT:
        return joined
    head = joined[:_STDERR_HEAD_CHARS]
    tail = joined[-(_STDERR_LOG_LIMIT - _STDERR_HEAD_CHARS) :]
    return f"{head} ...[{len(joined) - _STDERR_LOG_LIMIT} chars omitted]... {tail}"


# What the parsers osv-scanner embeds say when the document's spec version is
# newer than they know. CycloneDX's is the first line; SPDX phrases it as an
# unsupported version. Both arrive as the same generic extraction failure, so
# the wording is the only thing that separates them from a corrupt document.
_UNSUPPORTED_SPEC_VERSION_PHRASES = (
    "invalid specification version",
    "unsupported specversion",
    "unsupported spec version",
    "unsupported spdx version",
)


def _is_unsupported_spec_version(stderr: str) -> bool:
    """Whether osv-scanner refused the document over its spec version.

    Matched on stderr rather than on the exit code, because 127 is also the
    conventional shell code for "command not found" — a genuine failure that
    has to keep erroring. The scanner exits 127 for every extraction failure
    alike and says which one only in the message.

    Deliberately narrow, like the Dependency Track check it mirrors. A document
    that is actually malformed still gets its error result: reading a corrupt
    BOM as "not applicable" would hide the thing worth knowing.
    """
    haystack = (stderr or "").lower()
    return any(phrase in haystack for phrase in _UNSUPPORTED_SPEC_VERSION_PHRASES)


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
    # osv-scanner exits 0 when it matched nothing and 1 when it found
    # vulnerabilities. Every other code means the scan itself did not run to
    # completion, so its (empty) output says nothing about the SBOM.
    SUCCESS_EXIT_CODES = (0, 1)
    # Except this one: 128 is "no package sources found", which is the scanner
    # working correctly and having nothing to match — the case
    # ``_create_no_packages_result`` already exists for. Staging bears that out:
    # every exit-128 run was followed by the no-packages skip firing on its
    # stderr, while only exit 127 fell through to a clean result. Treating it as
    # a hard failure would turn a deliberate "Nothing scanned" into a
    # high-severity Scan Error for documents whose PURLs the scanner does not
    # recognise.
    NO_PACKAGE_SOURCES_EXIT_CODE = 128

    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        return PluginMetadata(
            name="osv",
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
        """Scan SBOM for vulnerabilities using osv-scanner.

        The orchestrator provides files with a generic .json suffix, but
        osv-scanner requires .cdx.json or .spdx.json for format detection.
        This method creates a correctly-suffixed copy in the same temp
        directory and cleans it up after scanning.

        Args:
            sbom_id: The SBOM's primary key (for logging/reference).
            sbom_path: Path to the SBOM file on disk.
            dependency_status: Not used by this plugin.
            context: Optional pre-computed SBOM metadata from the orchestrator.

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

            # "Nothing to scan" is reported as an exit code as well as on
            # stderr, and it is not a failure — checked before the abort guard
            # so it keeps the skipped result rather than being reclassified as
            # a high-severity error.
            if returncode == self.NO_PACKAGE_SOURCES_EXIT_CODE:
                logger.warning(
                    f"[OSV] Scan of SBOM {sbom_id} found no package sources; reporting as skipped rather than clean"
                )
                return self._create_no_packages_result()

            # A spec version the bundled scanner does not know is a capability
            # gap, not a fault: the scan never ran, but the artifact is fine and
            # a later osv-scanner reads it without anyone intervening. Reported
            # as an error it becomes a high-severity Scan Error on a valid SBOM,
            # again on every scheduled rescan. Same reasoning, and the same
            # answer, as the Dependency Track plugin gives for the same
            # documents. Checked before the abort guard so it keeps the skip.
            if returncode not in self.SUCCESS_EXIT_CODES and _is_unsupported_spec_version(stderr):
                logger.info(
                    f"[OSV] SBOM {sbom_id} uses a spec version this osv-scanner does not accept: "
                    f"{_collapse_for_log(stderr)}"
                )
                return self._create_unsupported_spec_version_result(stderr)

            # A scanner that aborted produces no findings for the same reason a
            # clean SBOM does — an empty result set — so the two are
            # indistinguishable downstream unless the exit code is checked
            # first. Falling through here published "0 vulnerabilities found"
            # for SBOMs osv-scanner never actually scanned.
            if returncode not in self.SUCCESS_EXIT_CODES:
                logger.error(f"[OSV] Scan of SBOM {sbom_id} failed with exit code {returncode}; reporting as error")
                return self._create_error_result(
                    f"osv-scanner exited with code {returncode} without completing the scan. "
                    "No vulnerability result can be inferred from this run."
                )

            # Parse results into findings
            findings = self._parse_scan_output(stdout, returncode)

            # No findings can mean two opposite things: nothing was vulnerable,
            # or nothing was recognised. A Yocto SPDX document carries
            # ``pkg:yocto/...`` PURLs, which osv-scanner rejects as invalid and
            # skips, and the scan reports "found 0 packages" while exiting
            # cleanly. Reported as a pass, that renders a green "no known
            # vulnerabilities" badge over a build nothing was ever matched
            # against — the worst answer a security product can give.
            if not findings and self._scanned_package_count(stderr) == 0:
                logger.warning(
                    f"[OSV] Scan of SBOM {sbom_id} recognised no packages; reporting as skipped rather than clean"
                )
                return self._create_no_packages_result()

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

        except subprocess.TimeoutExpired as exc:
            # The exception carries whatever the scanner managed to write before
            # it was killed, and that is the only account of where it stalled —
            # the lockfile it was on, a network retry loop, the ecosystem it was
            # resolving. Discarding it left the same "exit condition preserved,
            # reason discarded" gap on this path that the non-zero-exit path was
            # fixed for. Decoded defensively: stderr is bytes when the call was
            # made without text mode, and a partial read can be invalid UTF-8.
            raw = exc.stderr
            partial = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes | bytearray) else (raw or "")
            detail = _collapse_for_log(partial)
            logger.error(
                f"[OSV] Scanner timed out after {timeout}s for SBOM {sbom_id}"
                + (f": {detail}" if detail else " with no output")
            )
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
            "--lockfile",
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

        # Exit code 0 = no vulns, 1 = vulns found, 128 = nothing to scan,
        # anything else = the scan did not run to completion.
        #
        # Error rather than warning for the last group: it used to be advisory,
        # because the run carried on and published a result regardless, and it
        # is now the point at which the scan is abandoned. A line that reads as
        # non-fatal for an outcome the caller treats as fatal is what makes a
        # log hard to trust.
        #
        # 128 is excluded because assess() turns it into a skipped result, and
        # settings wires Sentry to capture on logger.error — so leaving it in
        # the error branch raised an incident for a Yocto SBOM the scanner
        # simply had no packages to match, every hour. A spec version the
        # scanner is too old to read is excluded for the same reason: assess()
        # skips it, and nobody should be paged because CycloneDX shipped a new
        # version.
        if process.returncode == self.NO_PACKAGE_SOURCES_EXIT_CODE:
            logger.warning(f"[OSV] Scanner found no package sources: {_collapse_for_log(process.stderr)}")
        elif process.returncode not in self.SUCCESS_EXIT_CODES:
            if _is_unsupported_spec_version(process.stderr):
                logger.warning(f"[OSV] Scanner does not read this spec version: {_collapse_for_log(process.stderr)}")
            else:
                logger.error(f"[OSV] Scanner returned code {process.returncode}: {_collapse_for_log(process.stderr)}")

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

        # 1. CVSS vector in the severity field. V3 is checked first and V4 only
        # as a fallback: both encode base score the same way, and preferring V3
        # keeps a finding's score stable across a rescan once OSV adds a V4
        # entry to a record that already had V3.
        for wanted in ("CVSS_V3", "CVSS_V4"):
            for severity_item in vuln.get("severity", []):
                if severity_item.get("type") == wanted:
                    score = self._extract_cvss_score(severity_item.get("score", ""))
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
        """Extract numeric CVSS score from a CVSS v3 or v4 vector string.

        Uses a regex to find the base score at the end of the vector.
        If that fails, uses simple heuristics on the vector components.

        Note: The heuristic fallback produces approximate scores based on
        impact metrics only: C/I/A and Scope for v3, and their v4 renames
        VC/VI/VA (4.0 having dropped Scope). It does not account for
        exploitability metrics (AV, AC, PR, UI), so scores may differ from
        a full CVSS calculation. This is acceptable because most OSV entries
        include a proper numeric score; the heuristic is a last resort.

        Args:
            cvss_string: CVSS v3 or v4 vector string (e.g. "CVSS:3.1/AV:N/..."
                or "CVSS:4.0/AV:N/...").

        Returns:
            Numeric CVSS score or None if the vector cannot be parsed.
        """
        if not cvss_string or not cvss_string.startswith(("CVSS:3", "CVSS:4")):
            return None

        # Try to extract trailing numeric score (some formats append it)
        score_match = re.search(r"/(\d+\.?\d*)$", cvss_string)
        if score_match:
            try:
                return float(score_match.group(1))
            except ValueError:
                pass

        # Heuristic scoring based on vector components. CVSS 4.0 renamed the
        # impact metrics to VC/VI/VA and dropped Scope, so the v3 substrings
        # never match a v4 vector and it would fall through to None.
        if cvss_string.startswith("CVSS:4"):
            if "VC:H/VI:H/VA:H" in cvss_string:
                return 9.0
            elif any(f"{m}:H" in cvss_string for m in ("VC", "VI", "VA")):
                return 7.5
            elif any(f"{m}:L" in cvss_string for m in ("VC", "VI", "VA")):
                return 4.0
            return None

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

    _SCANNED_PACKAGES = re.compile(r"found (\d+) package", re.IGNORECASE)

    def _scanned_package_count(self, stderr: str) -> int | None:
        """How many packages osv-scanner said it recognised, or None if it did not say.

        The count is only on stderr. The JSON output lists packages that *have*
        vulnerabilities, so on a clean scan it cannot distinguish "500 scanned,
        none vulnerable" from "none scanned at all".

        None rather than 0 when the line is absent: a scanner version that
        phrases it differently must not turn every clean scan into a skip.
        """
        match = self._SCANNED_PACKAGES.search(stderr or "")
        return int(match.group(1)) if match else None

    def _create_no_packages_result(self) -> AssessmentResult:
        """A scan that recognised nothing, reported as skipped rather than clean.

        Skipped is the shape that already means "the plugin never scanned
        anything" — ``public_assessment_utils._is_run_skipped`` reads it and
        withholds the public pass, which is the whole point here.
        """
        finding = Finding(
            id="osv:no-packages",
            title="No Packages Recognised",
            description=(
                "osv-scanner did not recognise any packages in this SBOM, so it was not "
                "matched against any advisory source. This usually means the package URLs "
                "use a type osv-scanner does not know, such as pkg:yocto. No vulnerability "
                "result can be inferred from this scan."
            ),
            status="warning",
            severity="info",
        )
        summary = AssessmentSummary(
            total_findings=1,
            pass_count=0,
            fail_count=0,
            warning_count=1,
            error_count=0,
        )
        return AssessmentResult(
            plugin_name="osv",
            plugin_version=self.VERSION,
            category=AssessmentCategory.SECURITY.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=[finding],
            metadata={"scanner": "osv-scanner", "skipped": True, "no_packages": True},
        )

    def _create_unsupported_spec_version_result(self, stderr: str) -> AssessmentResult:
        """A document the bundled scanner is too old to read, reported as skipped.

        ``unsupported_input`` is the marker the scheduled sweep's backoff reads:
        the next run gets the identical rejection, so re-scanning sooner than a
        scanner upgrade buys nothing. OSV's own sweeps already sit at a day and
        a week, which is longer than the backoff, so it changes nothing today —
        it is set because the marker means "the scanner cannot read this input"
        and this is that, and a shorter cadence must not have to remember.
        """
        return self.create_skipped_result(
            finding_id="osv:unsupported-spec-version",
            title="Spec Version Not Supported",
            description=(
                "osv-scanner does not read this SBOM's spec version yet, so it was not "
                "scanned for vulnerabilities. The SBOM itself is fine, and it will be "
                f"scanned once the scanner supports the version. Scanner output: {_collapse_for_log(stderr)}"
            ),
            unsupported_input=True,
            extra_metadata={"scanner": "osv-scanner", "unsupported_spec_version": True},
        )

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

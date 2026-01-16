"""GitHub Attestation plugin for verifying SBOM attestations.

This plugin verifies that an SBOM file itself has a valid GitHub attestation by:
1. Extracting VCS (GitHub) information from the SBOM's externalReferences
2. Downloading the attestation bundle from GitHub's public API
3. Running `cosign verify-blob-attestation` against the SBOM file
4. Returning pass/fail findings based on verification result
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from sbomify.apps.plugins.sdk.base import AssessmentPlugin
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.plugins.sdk.results import (
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
)
from sbomify.apps.plugins.utils import get_http_session
from sbomify.logging import getLogger

logger = getLogger(__name__)

# File reading chunk size for SBOM digest calculation.
# 8192 bytes (8 KiB) is a common default that aligns with typical OS
# page/block sizes and standard I/O buffering.
SBOM_FILE_READ_CHUNK_SIZE = 8192


class GitHubAttestationError(Exception):
    """Exception raised for GitHub attestation verification errors."""

    pass


class GitHubAttestationPlugin(AssessmentPlugin):
    """Plugin for verifying GitHub attestations on SBOM files.

    This plugin extracts VCS information from the SBOM and verifies
    that the SBOM file itself has a valid GitHub attestation using
    Sigstore/cosign.

    The verification flow:
    1. Extract GitHub org/repo from the SBOM's VCS references
    2. Calculate SHA256 digest of the SBOM file
    3. Download the attestation bundle from GitHub's public API
    4. Verify the SBOM file using `cosign verify-blob-attestation`

    No authentication is required for public repositories.

    Configuration options:
        certificate_identity_regexp: Pattern for certificate identity
            (default: GitHub Actions pattern for the extracted repo)
        certificate_oidc_issuer: Expected OIDC issuer
            (default: https://token.actions.githubusercontent.com)

    Example:
        >>> plugin = GitHubAttestationPlugin()
        >>> result = plugin.assess("sbom123", Path("/tmp/sbom.json"))
        >>> print(result.findings[0].status)
        'pass'
    """

    VERSION = "1.0.0"

    # Default configuration
    DEFAULT_CERTIFICATE_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
    DEFAULT_TIMEOUT = 60  # seconds

    def __init__(self, config: dict | None = None) -> None:
        """Initialize the plugin with configuration.

        Args:
            config: Plugin configuration with optional keys:
                - certificate_identity_regexp: Custom identity pattern
                - certificate_oidc_issuer: Custom OIDC issuer
                - timeout: Timeout in seconds for verification (default: 60)
        """
        super().__init__(config)
        self.certificate_oidc_issuer = self.config.get("certificate_oidc_issuer", self.DEFAULT_CERTIFICATE_OIDC_ISSUER)
        self.timeout = self.config.get("timeout", self.DEFAULT_TIMEOUT)

    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata.

        Returns:
            PluginMetadata with name "github-attestation", version "1.0.0",
            and category ATTESTATION.
        """
        return PluginMetadata(
            name="github-attestation",
            version=self.VERSION,
            category=AssessmentCategory.ATTESTATION,
        )

    def assess(self, sbom_id: str, sbom_path: Path) -> AssessmentResult:
        """Verify GitHub attestation for the SBOM file.

        This method:
        1. Parses the SBOM to extract VCS information (GitHub org/repo)
        2. Downloads the attestation bundle from GitHub
        3. Verifies the SBOM file using cosign verify-blob-attestation

        Args:
            sbom_id: The SBOM's primary key.
            sbom_path: Path to the SBOM file on disk.

        Returns:
            AssessmentResult with pass/fail finding based on verification.
        """
        bundle_path = None
        try:
            # Parse the SBOM
            sbom_data = json.loads(sbom_path.read_text())

            # Extract VCS information
            vcs_info = self._extract_vcs_info(sbom_data)
            if not vcs_info:
                return self._create_result_no_vcs_info(sbom_id)

            github_org = vcs_info.get("org")
            github_repo = vcs_info.get("repo")

            # Build certificate identity pattern
            certificate_identity_regexp = self.config.get(
                "certificate_identity_regexp",
                f"^https://github.com/{github_org}/{github_repo}/.*",
            )

            # Download attestation bundle from GitHub
            bundle_result = self._download_attestation_bundle(
                sbom_path=sbom_path,
                github_org=github_org,
                github_repo=github_repo,
            )

            if not bundle_result.get("success"):
                return self._create_result_no_attestation(
                    sbom_id=sbom_id,
                    github_org=github_org,
                    github_repo=github_repo,
                    error=bundle_result.get("error", "Unknown error"),
                )

            bundle_path = bundle_result.get("bundle_path")

            # Verify attestation using cosign verify-blob-attestation
            verification_result = self._verify_attestation(
                sbom_path=sbom_path,
                bundle_path=bundle_path,
                certificate_identity_regexp=certificate_identity_regexp,
            )

            return self._create_result(
                sbom_id=sbom_id,
                verification_result=verification_result,
                github_org=github_org,
                github_repo=github_repo,
                sbom_path=sbom_path,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse SBOM JSON: {e}")
            return self._create_result_error(sbom_id, f"Failed to parse SBOM JSON: {e}")
        except GitHubAttestationError as e:
            logger.error(f"GitHub attestation error: {e}")
            return self._create_result_error(sbom_id, str(e))
        except Exception as e:
            logger.exception(f"Unexpected error during attestation verification: {e}")
            return self._create_result_error(sbom_id, f"Unexpected error: {e}")
        finally:
            # Clean up temporary bundle file
            if bundle_path and os.path.exists(bundle_path):
                try:
                    os.unlink(bundle_path)
                except OSError as e:
                    logger.debug(f"Failed to clean up temporary bundle file {bundle_path}: {e}")

    def _extract_vcs_info(self, sbom_data: dict) -> dict[str, str] | None:
        """Extract VCS (GitHub) information from SBOM.

        Supports both CycloneDX and SPDX formats:

        CycloneDX:
        - metadata.component.externalReferences (type: vcs)
        - Top-level externalReferences
        - components[*].externalReferences

        SPDX:
        - packages[0].downloadLocation (git+url format)
        - packages[0].externalRefs (referenceType: vcs)

        Args:
            sbom_data: Parsed SBOM JSON data.

        Returns:
            Dict with 'org' and 'repo' keys, or None if not found.
        """
        # Detect format based on structure
        if self._is_spdx_format(sbom_data):
            return self._extract_vcs_info_spdx(sbom_data)
        else:
            return self._extract_vcs_info_cyclonedx(sbom_data)

    def _is_spdx_format(self, sbom_data: dict) -> bool:
        """Check if SBOM is in SPDX format.

        Args:
            sbom_data: Parsed SBOM JSON data.

        Returns:
            True if SPDX format, False otherwise.
        """
        return "spdxVersion" in sbom_data or "SPDXID" in sbom_data

    def _extract_vcs_info_cyclonedx(self, sbom_data: dict) -> dict[str, str] | None:
        """Extract VCS info from CycloneDX format.

        Args:
            sbom_data: Parsed CycloneDX SBOM JSON data.

        Returns:
            Dict with 'org' and 'repo' keys, or None.
        """
        # Check metadata.component.externalReferences first
        metadata = sbom_data.get("metadata", {})
        component = metadata.get("component", {})
        external_refs = component.get("externalReferences", [])

        vcs_url = self._find_vcs_url_cyclonedx(external_refs)
        if vcs_url:
            result = self._parse_github_url(vcs_url)
            if result:
                return result

        # If not found, check top-level externalReferences
        external_refs = sbom_data.get("externalReferences", [])
        vcs_url = self._find_vcs_url_cyclonedx(external_refs)
        if vcs_url:
            result = self._parse_github_url(vcs_url)
            if result:
                return result

        # If not found, check components for VCS references
        for comp in sbom_data.get("components", []):
            external_refs = comp.get("externalReferences", [])
            vcs_url = self._find_vcs_url_cyclonedx(external_refs)
            if vcs_url:
                result = self._parse_github_url(vcs_url)
                if result:
                    return result

        return None

    def _extract_vcs_info_spdx(self, sbom_data: dict) -> dict[str, str] | None:
        """Extract VCS info from SPDX format.

        Args:
            sbom_data: Parsed SPDX SBOM JSON data.

        Returns:
            Dict with 'org' and 'repo' keys, or None.
        """
        packages = sbom_data.get("packages", [])
        if not packages:
            return None

        main_pkg = packages[0]

        # Check downloadLocation for git+url format
        download_location = main_pkg.get("downloadLocation", "")
        if download_location and download_location not in ("NOASSERTION", "NONE"):
            vcs_url = self._parse_spdx_download_location(download_location)
            if vcs_url:
                result = self._parse_github_url(vcs_url)
                if result:
                    return result

        # Check externalRefs for VCS reference
        external_refs = main_pkg.get("externalRefs", [])
        for ref in external_refs:
            ref_type = ref.get("referenceType", "").lower()
            if ref_type == "vcs":
                locator = ref.get("referenceLocator", "")
                if locator:
                    result = self._parse_github_url(locator)
                    if result:
                        return result

        return None

    def _parse_spdx_download_location(self, download_location: str) -> str | None:
        """Parse SPDX downloadLocation to extract VCS URL.

        Handles format: git+https://github.com/org/repo[@commit_sha]

        Args:
            download_location: The downloadLocation string.

        Returns:
            VCS URL string or None.
        """
        if not download_location.startswith("git+"):
            return None

        # Remove git+ prefix
        url_part = download_location[4:]

        # Split on @ to get URL (ignore commit part)
        if "@" in url_part:
            url_part = url_part.rsplit("@", 1)[0]

        return url_part

    def _find_vcs_url_cyclonedx(self, external_refs: list[dict]) -> str | None:
        """Find a VCS URL from CycloneDX external references.

        Args:
            external_refs: List of external reference objects.

        Returns:
            VCS URL string or None.
        """
        for ref in external_refs:
            ref_type = ref.get("type", "").lower()
            url = ref.get("url", "")

            # CycloneDX uses "vcs" type
            if ref_type == "vcs" and self._is_github_url(url):
                return url

            # Also check for git type
            if ref_type == "git" and self._is_github_url(url):
                return url

        return None

    def _is_github_url(self, url: str) -> bool:
        """Check if URL is a valid GitHub URL using proper URL parsing.

        This method prevents URL bypass attacks by properly parsing the URL
        and checking the hostname, rather than using substring matching.

        Args:
            url: URL string to check.

        Returns:
            True if URL is from github.com, False otherwise.
        """
        if not url:
            return False

        # Handle SSH URLs (git@github.com:...)
        if url.startswith("git@github.com:"):
            return True

        # Parse HTTPS URLs properly
        try:
            parsed = urlparse(url)
            # Check that the hostname is exactly github.com (not a subdomain or different domain)
            return parsed.netloc == "github.com"
        except Exception:
            return False

    def _parse_github_url(self, url: str) -> dict[str, str] | None:
        """Parse GitHub URL to extract org and repo.

        Handles various GitHub URL formats:
        - https://github.com/org/repo
        - https://github.com/org/repo.git
        - https://github.com/org/repo@commit_hash
        - git@github.com:org/repo.git

        Args:
            url: GitHub URL string.

        Returns:
            Dict with 'org' and 'repo' keys, or None if parsing fails.
        """
        # Handle SSH URLs
        if url.startswith("git@github.com:"):
            path = url.replace("git@github.com:", "").rstrip(".git")
            parts = path.split("/")
            if len(parts) >= 2:
                repo = parts[1].split("@")[0]  # Strip commit reference
                return {"org": parts[0], "repo": repo}
            return None

        # Handle HTTPS URLs
        try:
            parsed = urlparse(url)
            # Properly validate hostname to prevent bypass attacks
            if parsed.netloc != "github.com":
                return None

            path = parsed.path.strip("/").rstrip(".git")
            parts = path.split("/")
            if len(parts) >= 2:
                repo = parts[1].split("@")[0]  # Strip commit reference
                return {"org": parts[0], "repo": repo}
        except Exception as e:
            logger.warning(f"Failed to parse GitHub URL '{url}': {e}")

        return None

    def _calculate_file_digest(self, file_path: Path) -> str:
        """Calculate SHA256 digest of a file.

        Args:
            file_path: Path to the file.

        Returns:
            SHA256 digest as hex string.
        """
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(SBOM_FILE_READ_CHUNK_SIZE), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def _download_attestation_bundle(
        self,
        sbom_path: Path,
        github_org: str,
        github_repo: str,
    ) -> dict[str, Any]:
        """Download attestation bundle from GitHub's public API.

        No authentication is required for public repositories.

        Args:
            sbom_path: Path to the SBOM file.
            github_org: GitHub organization name.
            github_repo: GitHub repository name.

        Returns:
            Dict with:
                - success: bool
                - bundle_path: Path to downloaded bundle (if successful)
                - error: Error message (if failed)
        """
        # Calculate SHA256 digest of the SBOM file
        try:
            file_digest = self._calculate_file_digest(sbom_path)
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to calculate file digest: {e}",
            }

        # GitHub Attestations API endpoint
        # https://docs.github.com/en/rest/users/attestations
        api_url = f"https://api.github.com/repos/{github_org}/{github_repo}/attestations/sha256:{file_digest}"

        logger.info(f"Fetching attestation from {api_url}")

        try:
            session = get_http_session()
            response = session.get(
                api_url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=self.timeout,
            )

            if response.status_code == 404:
                return {
                    "success": False,
                    "error": f"No attestation found for this SBOM (digest: sha256:{file_digest})",
                }

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"GitHub API error: {response.status_code} - {response.text}",
                }

            data = response.json()
            attestations = data.get("attestations", [])

            if not attestations:
                return {
                    "success": False,
                    "error": "No attestations returned from GitHub API",
                }

            # Get the first attestation bundle
            # The bundle is in the format expected by cosign
            bundle = attestations[0].get("bundle")
            if not bundle:
                return {
                    "success": False,
                    "error": "Attestation response missing bundle data",
                }

            # Write bundle to temporary file with secure permissions.
            # mkstemp creates files with 0o600 permissions by default, avoiding
            # the race condition of setting permissions after file creation.
            temp_path = None
            try:
                fd, temp_path = tempfile.mkstemp(suffix=".json")
                with os.fdopen(fd, "w") as f:
                    json.dump(bundle, f)
                return {
                    "success": True,
                    "bundle_path": Path(temp_path),
                }
            except Exception as e:
                # Clean up temp file if it was created
                if temp_path:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
                return {
                    "success": False,
                    "error": f"Failed to write bundle file: {e}",
                }

        except requests.Timeout:
            return {
                "success": False,
                "error": "Attestation bundle download timed out",
            }
        except requests.RequestException as e:
            return {
                "success": False,
                "error": f"Error fetching attestation from GitHub: {e}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error downloading attestation: {e}",
            }

    def _verify_attestation(
        self,
        sbom_path: Path,
        bundle_path: Path,
        certificate_identity_regexp: str,
    ) -> dict[str, Any]:
        """Verify attestation using cosign verify-blob-attestation.

        Args:
            sbom_path: Path to the SBOM file to verify.
            bundle_path: Path to the attestation bundle downloaded from GitHub.
            certificate_identity_regexp: Pattern for certificate identity.

        Returns:
            Dict with verification result including:
                - verified: bool
                - message: str
                - details: dict (optional)
        """
        # Check if cosign is available
        cosign_path = shutil.which("cosign")
        if not cosign_path:
            raise GitHubAttestationError("cosign binary not found. Please ensure cosign is installed.")

        # Build cosign verify-blob-attestation command
        # --new-bundle-format is required for Sigstore bundle v0.3 (used by GitHub)
        cmd = [
            cosign_path,
            "verify-blob-attestation",
            "--bundle",
            str(bundle_path),
            "--new-bundle-format",
            "--certificate-identity-regexp",
            certificate_identity_regexp,
            "--certificate-oidc-issuer",
            self.certificate_oidc_issuer,
            str(sbom_path),
        ]

        logger.info(f"Running cosign verify-blob-attestation for {sbom_path}")
        logger.debug(f"Cosign command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            if result.returncode == 0:
                return {
                    "verified": True,
                    "message": "SBOM attestation verified successfully",
                    "details": {
                        "sbom_file": str(sbom_path),
                        "certificate_identity": certificate_identity_regexp,
                        "oidc_issuer": self.certificate_oidc_issuer,
                    },
                }
            else:
                error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
                return {
                    "verified": False,
                    "message": f"Attestation verification failed: {error_msg}",
                    "details": {
                        "sbom_file": str(sbom_path),
                        "error": error_msg,
                        "exit_code": result.returncode,
                    },
                }

        except subprocess.TimeoutExpired:
            return {
                "verified": False,
                "message": "Attestation verification timed out",
                "details": {"sbom_file": str(sbom_path), "error": "timeout"},
            }
        except Exception as e:
            return {
                "verified": False,
                "message": f"Error running cosign: {e}",
                "details": {"sbom_file": str(sbom_path), "error": str(e)},
            }

    def _create_result(
        self,
        sbom_id: str,
        verification_result: dict[str, Any],
        github_org: str,
        github_repo: str,
        sbom_path: Path,
    ) -> AssessmentResult:
        """Create assessment result from verification outcome.

        Args:
            sbom_id: The SBOM ID.
            verification_result: Result from _verify_attestation.
            github_org: GitHub organization.
            github_repo: GitHub repository.
            sbom_path: Path to the verified SBOM file.

        Returns:
            AssessmentResult with appropriate findings.
        """
        verified = verification_result.get("verified", False)
        message = verification_result.get("message", "")
        details = verification_result.get("details", {})

        # Build base metadata
        base_metadata = {
            "github_org": github_org,
            "github_repo": github_repo,
            "sbom_file": str(sbom_path),
        }

        if verified:
            finding = Finding(
                id="github-attestation:verified",
                title="GitHub Attestation Verified",
                description=f"Successfully verified SBOM attestation from {github_org}/{github_repo}",
                status="pass",
                severity="info",
                metadata={
                    **base_metadata,
                    **details,
                },
            )
            summary = AssessmentSummary(
                total_findings=1,
                pass_count=1,
                fail_count=0,
            )
        else:
            finding = Finding(
                id="github-attestation:failed",
                title="GitHub Attestation Verification Failed",
                description=message,
                status="fail",
                severity="high",
                metadata={
                    **base_metadata,
                    **details,
                },
            )
            summary = AssessmentSummary(
                total_findings=1,
                pass_count=0,
                fail_count=1,
            )

        return AssessmentResult(
            plugin_name="github-attestation",
            plugin_version=self.VERSION,
            category=AssessmentCategory.ATTESTATION.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=[finding],
            metadata={"sbom_id": sbom_id},
        )

    def _create_result_no_vcs_info(self, sbom_id: str) -> AssessmentResult:
        """Create result when no VCS information is found.

        Args:
            sbom_id: The SBOM ID.

        Returns:
            AssessmentResult with warning finding.
        """
        finding = Finding(
            id="github-attestation:no-vcs",
            title="No GitHub VCS Information Found",
            description=(
                "Could not find GitHub VCS information in the SBOM. "
                "Ensure the SBOM includes externalReferences with type 'vcs' "
                "pointing to a GitHub repository."
            ),
            status="warning",
            severity="info",
        )

        return AssessmentResult(
            plugin_name="github-attestation",
            plugin_version=self.VERSION,
            category=AssessmentCategory.ATTESTATION.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=AssessmentSummary(
                total_findings=1,
                pass_count=0,
                fail_count=0,
                warning_count=1,
            ),
            findings=[finding],
            metadata={"sbom_id": sbom_id},
        )

    def _create_result_no_attestation(
        self,
        sbom_id: str,
        github_org: str | None,
        github_repo: str | None,
        error: str,
    ) -> AssessmentResult:
        """Create result when no attestation is found for the SBOM.

        Args:
            sbom_id: The SBOM ID.
            github_org: GitHub organization (if found).
            github_repo: GitHub repository (if found).
            error: Error message from attestation download attempt.

        Returns:
            AssessmentResult with fail finding.
        """
        finding = Finding(
            id="github-attestation:no-attestation",
            title="No GitHub Attestation Found",
            description=(
                f"Could not download attestation from GitHub for this SBOM. "
                f"Ensure the SBOM was generated by a GitHub Actions workflow with "
                f"artifact attestations enabled. Error: {error}"
            ),
            status="fail",
            severity="high",
            metadata={
                "github_org": github_org,
                "github_repo": github_repo,
                "error": error,
            },
        )

        return AssessmentResult(
            plugin_name="github-attestation",
            plugin_version=self.VERSION,
            category=AssessmentCategory.ATTESTATION.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=AssessmentSummary(
                total_findings=1,
                pass_count=0,
                fail_count=1,
            ),
            findings=[finding],
            metadata={"sbom_id": sbom_id},
        )

    def _create_result_error(self, sbom_id: str, error_message: str) -> AssessmentResult:
        """Create result for error conditions.

        Args:
            sbom_id: The SBOM ID.
            error_message: Description of the error.

        Returns:
            AssessmentResult with error finding.
        """
        finding = Finding(
            id="github-attestation:error",
            title="Attestation Verification Error",
            description=error_message,
            status="error",
            severity="high",
        )

        return AssessmentResult(
            plugin_name="github-attestation",
            plugin_version=self.VERSION,
            category=AssessmentCategory.ATTESTATION.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=AssessmentSummary(
                total_findings=1,
                pass_count=0,
                fail_count=0,
                warning_count=0,
                error_count=1,
            ),
            findings=[finding],
            metadata={"sbom_id": sbom_id, "error": error_message},
        )

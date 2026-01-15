"""GitHub Attestation plugin for verifying SBOM attestations.

This plugin verifies that an SBOM has a valid GitHub attestation by:
1. Extracting VCS (GitHub) information from the SBOM's externalReferences
2. Running `cosign verify-attestation` against the derived artifact
3. Returning pass/fail findings based on verification result
"""

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


class GitHubAttestationError(Exception):
    """Exception raised for GitHub attestation verification errors."""

    pass


class GitHubAttestationPlugin(AssessmentPlugin):
    """Plugin for verifying GitHub attestations on SBOMs.

    This plugin extracts VCS information from the SBOM and verifies
    that the associated artifact has a valid GitHub attestation using
    Sigstore/cosign.

    Configuration options:
        certificate_identity_regexp: Pattern for certificate identity
            (default: GitHub Actions pattern for the extracted repo)
        certificate_oidc_issuer: Expected OIDC issuer
            (default: https://token.actions.githubusercontent.com)
        attestation_type: Type of attestation to verify
            (default: https://slsa.dev/provenance/v1)

    Example:
        >>> plugin = GitHubAttestationPlugin()
        >>> result = plugin.assess("sbom123", Path("/tmp/sbom.json"))
        >>> print(result.findings[0].status)
        'pass'
    """

    VERSION = "1.0.0"

    # Default configuration
    DEFAULT_CERTIFICATE_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
    DEFAULT_ATTESTATION_TYPE = "https://slsa.dev/provenance/v1"
    DEFAULT_TIMEOUT = 60  # seconds

    def __init__(self, config: dict | None = None) -> None:
        """Initialize the plugin with configuration.

        Args:
            config: Plugin configuration with optional keys:
                - certificate_identity_regexp: Custom identity pattern
                - certificate_oidc_issuer: Custom OIDC issuer
                - attestation_type: Custom attestation type
                - timeout: Timeout in seconds for cosign verification (default: 60)
        """
        super().__init__(config)
        self.certificate_oidc_issuer = self.config.get("certificate_oidc_issuer", self.DEFAULT_CERTIFICATE_OIDC_ISSUER)
        self.attestation_type = self.config.get("attestation_type", self.DEFAULT_ATTESTATION_TYPE)
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
        """Verify GitHub attestation for the SBOM.

        This method:
        1. Parses the SBOM to extract VCS information
        2. Derives the GitHub org/repo from the VCS URL
        3. Extracts the attestation target (container image) from the SBOM
        4. Runs cosign verify-attestation

        Args:
            sbom_id: The SBOM's primary key.
            sbom_path: Path to the SBOM file on disk.

        Returns:
            AssessmentResult with pass/fail finding based on verification.
        """
        try:
            # Parse the SBOM
            sbom_data = json.loads(sbom_path.read_text())

            # Extract VCS information
            vcs_info = self._extract_vcs_info(sbom_data)
            if not vcs_info:
                return self._create_result_no_vcs_info(sbom_id)

            github_org = vcs_info.get("org")
            github_repo = vcs_info.get("repo")
            commit_sha = vcs_info.get("commit_sha")

            # Extract attestation target (container image reference)
            attestation_target = self._extract_attestation_target(sbom_data)
            if not attestation_target:
                return self._create_result_no_attestation_target(sbom_id, github_org, github_repo)

            # Validate attestation target format
            if not self._validate_attestation_target(attestation_target):
                return self._create_result_error(sbom_id, f"Invalid attestation target format: {attestation_target}")

            # Build certificate identity pattern
            certificate_identity_regexp = self.config.get(
                "certificate_identity_regexp",
                f"^https://github.com/{github_org}/{github_repo}/.*",
            )

            # Verify attestation using cosign
            verification_result = self._verify_attestation(
                attestation_target=attestation_target,
                certificate_identity_regexp=certificate_identity_regexp,
                github_org=github_org,
                github_repo=github_repo,
            )

            return self._create_result(
                sbom_id=sbom_id,
                verification_result=verification_result,
                github_org=github_org,
                github_repo=github_repo,
                attestation_target=attestation_target,
                commit_sha=commit_sha,
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

    def _extract_vcs_info(self, sbom_data: dict) -> dict[str, str] | None:
        """Extract VCS (GitHub) information from SBOM.

        Supports both CycloneDX and SPDX formats:

        CycloneDX:
        - metadata.component.externalReferences (type: vcs)
        - metadata.component.pedigree.commits (for commit SHA)
        - Top-level externalReferences
        - components[*].externalReferences

        SPDX:
        - packages[0].downloadLocation (git+url@sha format)
        - packages[0].externalRefs (referenceType: vcs)
        - creationInfo.creatorComment

        Args:
            sbom_data: Parsed SBOM JSON data.

        Returns:
            Dict with 'org', 'repo', and optionally 'commit_sha' keys, or None if not found.
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
            Dict with 'org', 'repo', and optionally 'commit_sha' keys, or None.
        """
        result = None

        # Check metadata.component.externalReferences first
        metadata = sbom_data.get("metadata", {})
        component = metadata.get("component", {})
        external_refs = component.get("externalReferences", [])

        vcs_url = self._find_vcs_url_cyclonedx(external_refs)
        if vcs_url:
            result = self._parse_github_url(vcs_url)

        # If not found, check top-level externalReferences
        if not result:
            external_refs = sbom_data.get("externalReferences", [])
            vcs_url = self._find_vcs_url_cyclonedx(external_refs)
            if vcs_url:
                result = self._parse_github_url(vcs_url)

        # If not found, check components for VCS references
        if not result:
            for comp in sbom_data.get("components", []):
                external_refs = comp.get("externalReferences", [])
                vcs_url = self._find_vcs_url_cyclonedx(external_refs)
                if vcs_url:
                    result = self._parse_github_url(vcs_url)
                    break

        # Extract commit SHA from pedigree if available
        if result:
            pedigree = component.get("pedigree", {})
            commits = pedigree.get("commits", [])
            if commits:
                # Get the first commit (most recent)
                first_commit = commits[0] if isinstance(commits, list) else None
                if first_commit:
                    commit_sha = first_commit.get("uid", "")
                    if commit_sha:
                        result["commit_sha"] = commit_sha

        return result

    def _extract_vcs_info_spdx(self, sbom_data: dict) -> dict[str, str] | None:
        """Extract VCS info from SPDX format.

        Args:
            sbom_data: Parsed SPDX SBOM JSON data.

        Returns:
            Dict with 'org', 'repo', and optionally 'commit_sha' keys, or None.
        """
        packages = sbom_data.get("packages", [])
        if not packages:
            return None

        main_pkg = packages[0]
        result = None
        commit_sha = None

        # Check downloadLocation for git+url@sha format
        download_location = main_pkg.get("downloadLocation", "")
        if download_location and download_location not in ("NOASSERTION", "NONE"):
            vcs_url, commit_sha = self._parse_spdx_download_location(download_location)
            if vcs_url:
                result = self._parse_github_url(vcs_url)

        # Check externalRefs for VCS reference
        if not result:
            external_refs = main_pkg.get("externalRefs", [])
            for ref in external_refs:
                ref_type = ref.get("referenceType", "").lower()
                if ref_type == "vcs":
                    locator = ref.get("referenceLocator", "")
                    if locator and "github.com" in locator:
                        result = self._parse_github_url(locator)
                        # Try to extract commit from comment
                        comment = ref.get("comment", "")
                        if comment and "commit:" in comment.lower():
                            match = re.search(r"commit:\s*([a-f0-9]+)", comment, re.IGNORECASE)
                            if match:
                                commit_sha = match.group(1)
                        break

        # Try to extract commit from sourceInfo
        if result and not commit_sha:
            source_info = main_pkg.get("sourceInfo", "")
            if source_info:
                match = re.search(r"commit\s+([a-f0-9]{7,40})", source_info, re.IGNORECASE)
                if match:
                    commit_sha = match.group(1)

        # Try to extract from creatorComment
        if result and not commit_sha:
            creation_info = sbom_data.get("creationInfo", {})
            creator_comment = creation_info.get("creatorComment", "")
            if creator_comment:
                # Pattern: "at {sha}" at the end
                match = re.search(r"at\s+([a-f0-9]{7,40})$", creator_comment)
                if match:
                    commit_sha = match.group(1)

        if result and commit_sha:
            result["commit_sha"] = commit_sha

        return result

    def _parse_spdx_download_location(self, download_location: str) -> tuple[str | None, str | None]:
        """Parse SPDX downloadLocation to extract VCS URL and commit SHA.

        Handles format: git+https://github.com/org/repo@commit_sha

        Args:
            download_location: The downloadLocation string.

        Returns:
            Tuple of (vcs_url, commit_sha) or (None, None).
        """
        if not download_location.startswith("git+"):
            return None, None

        # Remove git+ prefix
        url_part = download_location[4:]

        # Split on @ to get URL and commit
        if "@" in url_part:
            parts = url_part.rsplit("@", 1)
            vcs_url = parts[0]
            commit_sha = parts[1] if len(parts) > 1 else None
            return vcs_url, commit_sha

        return url_part, None

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
            if ref_type == "vcs" and "github.com" in url:
                return url

            # Also check for git type
            if ref_type == "git" and "github.com" in url:
                return url

        return None

    def _parse_github_url(self, url: str) -> dict[str, str] | None:
        """Parse GitHub URL to extract org and repo.

        Handles various GitHub URL formats:
        - https://github.com/org/repo
        - https://github.com/org/repo.git
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
                return {"org": parts[0], "repo": parts[1]}
            return None

        # Handle HTTPS URLs
        try:
            parsed = urlparse(url)
            if "github.com" not in parsed.netloc:
                return None

            path = parsed.path.strip("/").rstrip(".git")
            parts = path.split("/")
            if len(parts) >= 2:
                return {"org": parts[0], "repo": parts[1]}
        except Exception as e:
            logger.warning(f"Failed to parse GitHub URL '{url}': {e}")

        return None

    def _extract_attestation_target(self, sbom_data: dict) -> str | None:
        """Extract the attestation target from SBOM.

        Supports both CycloneDX and SPDX formats.

        The attestation target is typically a container image reference
        that can be found in:

        CycloneDX:
        - metadata.component with purl containing type=oci or type=docker
        - externalReferences with type 'distribution' or 'distribution-intake'
        - Component name + SHA-256 hash

        SPDX:
        - packages[0].downloadLocation (if it's a container image URL)
        - packages[0].externalRefs with referenceType 'purl' containing OCI/Docker
        - Package name if it looks like a container image

        Args:
            sbom_data: Parsed SBOM JSON data.

        Returns:
            Attestation target string (e.g., "ghcr.io/org/repo@sha256:...")
            or None if not found.
        """
        # Detect format and use appropriate extraction method
        if self._is_spdx_format(sbom_data):
            return self._extract_attestation_target_spdx(sbom_data)
        else:
            return self._extract_attestation_target_cyclonedx(sbom_data)

    def _extract_attestation_target_cyclonedx(self, sbom_data: dict) -> str | None:
        """Extract attestation target from CycloneDX format.

        Args:
            sbom_data: Parsed CycloneDX SBOM JSON data.

        Returns:
            Attestation target string or None.
        """
        metadata = sbom_data.get("metadata", {})
        component = metadata.get("component", {})

        # Check for purl in main component
        purl = component.get("purl", "")
        if purl:
            target = self._purl_to_image_reference(purl)
            if target:
                return target

        # Check externalReferences for distribution URLs
        external_refs = component.get("externalReferences", [])
        for ref in external_refs:
            ref_type = ref.get("type", "").lower()
            url = ref.get("url", "")

            if ref_type in ("distribution", "distribution-intake"):
                # Check if it looks like a container image reference
                if self._is_container_image_url(url):
                    return url

        # Check for hashes that could be used with GitHub attestation
        # GitHub attestation works with artifact digest
        hashes = component.get("hashes", [])
        for hash_entry in hashes:
            if hash_entry.get("alg", "").upper() == "SHA-256":
                digest = hash_entry.get("content", "")
                if digest:
                    # If we have the component name and digest, construct reference
                    name = component.get("name", "")
                    if name and "/" in name:
                        return f"{name}@sha256:{digest}"

        return None

    def _extract_attestation_target_spdx(self, sbom_data: dict) -> str | None:
        """Extract attestation target from SPDX format.

        Args:
            sbom_data: Parsed SPDX SBOM JSON data.

        Returns:
            Attestation target string or None.
        """
        packages = sbom_data.get("packages", [])
        if not packages:
            return None

        main_pkg = packages[0]

        # Check for purl in externalRefs
        external_refs = main_pkg.get("externalRefs", [])
        for ref in external_refs:
            ref_type = ref.get("referenceType", "").lower()
            if ref_type == "purl":
                locator = ref.get("referenceLocator", "")
                if locator:
                    target = self._purl_to_image_reference(locator)
                    if target:
                        return target

        # Check downloadLocation for container image URL
        download_location = main_pkg.get("downloadLocation", "")
        if download_location and download_location not in ("NOASSERTION", "NONE"):
            # Check if it's a container image URL (not a git+ URL)
            if not download_location.startswith("git+") and self._is_container_image_url(download_location):
                return download_location

        # Check if package name looks like a container image
        name = main_pkg.get("name", "")
        if name and self._is_container_image_url(name):
            # Try to find a checksum to construct a full reference
            checksums = main_pkg.get("checksums", [])
            for checksum in checksums:
                if checksum.get("algorithm", "").upper() == "SHA256":
                    digest = checksum.get("checksumValue", "")
                    if digest:
                        return f"{name}@sha256:{digest}"
            # Return just the name if no checksum
            return name

        return None

    def _purl_to_image_reference(self, purl: str) -> str | None:
        """Convert a Package URL to a container image reference.

        Args:
            purl: Package URL string.

        Returns:
            Container image reference or None.
        """
        # Check for OCI or Docker type purls
        # Format: pkg:oci/image@sha256:digest or pkg:docker/image@digest
        if not purl.startswith(("pkg:oci/", "pkg:docker/")):
            return None

        try:
            # Remove the pkg:oci/ or pkg:docker/ prefix
            if purl.startswith("pkg:oci/"):
                remainder = purl[8:]
            else:
                remainder = purl[11:]

            # Parse the purl format: namespace/name@version?qualifiers
            # or just name@version
            parts = remainder.split("?")[0]  # Remove qualifiers

            # Handle version/digest
            if "@" in parts:
                name_part, version = parts.split("@", 1)
                # Reconstruct the image reference
                # The name_part may contain the registry
                return f"{name_part}@{version}" if "sha256:" in version else f"{name_part}:{version}"

            return None
        except Exception as e:
            logger.warning(f"Failed to parse purl '{purl}': {e}")
            return None

    def _is_container_image_url(self, url: str) -> bool:
        """Check if a URL looks like a container image reference.

        Args:
            url: URL string to check.

        Returns:
            True if it looks like a container image reference.
        """
        container_registries = [
            "ghcr.io",
            "docker.io",
            "gcr.io",
            "registry.hub.docker.com",
            "quay.io",
            "ecr.aws",
            ".dkr.ecr.",
            "azurecr.io",
        ]
        return any(registry in url for registry in container_registries)

    def _validate_attestation_target(self, target: str) -> bool:
        """Validate that the attestation target is a valid container image reference.

        This provides basic input validation to prevent malformed input
        being passed to the cosign subprocess.

        Valid formats:
        - registry/repo@sha256:digest (e.g., ghcr.io/org/repo@sha256:abc123)
        - registry/repo:tag (e.g., docker.io/library/nginx:latest)
        - registry/repo (e.g., ghcr.io/org/repo)

        Args:
            target: The attestation target string to validate.

        Returns:
            True if the target appears to be a valid container image reference.
        """
        if not target or not isinstance(target, str):
            return False

        # Reject obviously dangerous patterns
        dangerous_patterns = [";", "|", "&", "$", "`", "\n", "\r", "$(", "${"]
        if any(pattern in target for pattern in dangerous_patterns):
            logger.warning(f"Attestation target contains dangerous characters: {target}")
            return False

        # Must contain at least one slash (registry/repo format)
        if "/" not in target:
            return False

        # Basic format validation: should match registry/path[@:version]
        # Allow alphanumeric, dots, dashes, underscores, slashes, colons, and @
        valid_pattern = re.compile(r"^[a-zA-Z0-9._\-/:@]+$")
        if not valid_pattern.match(target):
            logger.warning(f"Attestation target has invalid characters: {target}")
            return False

        # If it has @, it should be followed by sha256: or similar
        if "@" in target:
            parts = target.split("@", 1)
            if len(parts) == 2:
                # Version part should look like sha256:hex or a valid tag
                version = parts[1]
                if not (
                    version.startswith("sha256:")
                    or version.startswith("sha512:")
                    or re.match(r"^[a-zA-Z0-9._\-]+$", version)
                ):
                    return False

        return True

    def _verify_attestation(
        self,
        attestation_target: str,
        certificate_identity_regexp: str,
        github_org: str,
        github_repo: str,
    ) -> dict[str, Any]:
        """Verify attestation using cosign.

        Args:
            attestation_target: The artifact to verify (e.g., container image).
            certificate_identity_regexp: Pattern for certificate identity.
            github_org: GitHub organization name.
            github_repo: GitHub repository name.

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

        # Build cosign command
        cmd = [
            cosign_path,
            "verify-attestation",
            "--type",
            self.attestation_type,
            "--certificate-identity-regexp",
            certificate_identity_regexp,
            "--certificate-oidc-issuer",
            self.certificate_oidc_issuer,
            attestation_target,
        ]

        logger.info(f"Running cosign verify-attestation for {attestation_target}")
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
                    "message": "Attestation verified successfully",
                    "details": {
                        "attestation_target": attestation_target,
                        "certificate_identity": certificate_identity_regexp,
                        "oidc_issuer": self.certificate_oidc_issuer,
                        "attestation_type": self.attestation_type,
                    },
                }
            else:
                error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
                return {
                    "verified": False,
                    "message": f"Attestation verification failed: {error_msg}",
                    "details": {
                        "attestation_target": attestation_target,
                        "error": error_msg,
                        "exit_code": result.returncode,
                    },
                }

        except subprocess.TimeoutExpired:
            return {
                "verified": False,
                "message": "Attestation verification timed out",
                "details": {"attestation_target": attestation_target, "error": "timeout"},
            }
        except Exception as e:
            return {
                "verified": False,
                "message": f"Error running cosign: {e}",
                "details": {"attestation_target": attestation_target, "error": str(e)},
            }

    def _create_result(
        self,
        sbom_id: str,
        verification_result: dict[str, Any],
        github_org: str,
        github_repo: str,
        attestation_target: str,
        commit_sha: str | None = None,
    ) -> AssessmentResult:
        """Create assessment result from verification outcome.

        Args:
            sbom_id: The SBOM ID.
            verification_result: Result from _verify_attestation.
            github_org: GitHub organization.
            github_repo: GitHub repository.
            attestation_target: The verified artifact.
            commit_sha: Git commit SHA if available.

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
            "attestation_target": attestation_target,
        }
        if commit_sha:
            base_metadata["commit_sha"] = commit_sha

        if verified:
            finding = Finding(
                id="github-attestation:verified",
                title="GitHub Attestation Verified",
                description=f"Successfully verified attestation for {attestation_target}",
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

    def _create_result_no_attestation_target(
        self, sbom_id: str, github_org: str | None, github_repo: str | None
    ) -> AssessmentResult:
        """Create result when no attestation target is found.

        Args:
            sbom_id: The SBOM ID.
            github_org: GitHub organization (if found).
            github_repo: GitHub repository (if found).

        Returns:
            AssessmentResult with warning finding.
        """
        finding = Finding(
            id="github-attestation:no-target",
            title="No Attestation Target Found",
            description=(
                "Could not determine the attestation target from the SBOM. "
                "Ensure the SBOM includes a container image reference (purl with type oci/docker) "
                "or a distribution URL for the artifact to verify."
            ),
            status="warning",
            severity="info",
            metadata={
                "github_org": github_org,
                "github_repo": github_repo,
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
                fail_count=0,
                warning_count=1,
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

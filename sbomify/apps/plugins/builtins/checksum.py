"""Checksum plugin for SBOM integrity verification.

This plugin verifies the integrity of SBOMs by computing a SHA256 hash of the
file content and comparing it against the stored hash in the database.
"""

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sbomify.apps.plugins.sdk.base import AssessmentPlugin, SBOMContext
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.plugins.sdk.results import (
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
)


class ChecksumPlugin(AssessmentPlugin):
    """SBOM integrity verification plugin.

    This plugin verifies the integrity of SBOM files by:
    1. Computing the SHA256 hash of the SBOM file content
    2. Comparing it against the stored hash in the database (from SBOMContext)

    When the hashes match, the plugin produces a "pass" finding confirming
    the SBOM content has not been modified since upload. When they differ,
    it produces a "fail" finding indicating potential corruption or tampering.

    If no stored hash is available (legacy SBOMs uploaded before hash tracking),
    the plugin produces a "warning" finding with the computed hash.

    Example:
        >>> plugin = ChecksumPlugin()
        >>> context = SBOMContext(sha256_hash="a1b2c3d4...")
        >>> result = plugin.assess("sbom123", Path("/tmp/sbom.json"), context)
        >>> print(result.findings[0].status)
        'pass'  # if hashes match
    """

    VERSION = "1.1.0"

    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata.

        Returns:
            PluginMetadata with name "checksum", version "1.1.0",
            and category COMPLIANCE.
        """
        return PluginMetadata(
            name="checksum",
            version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE,
        )

    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict | None = None,
        context: SBOMContext | None = None,
    ) -> AssessmentResult:
        """Verify SBOM integrity by comparing computed and stored hashes.

        Args:
            sbom_id: The SBOM's primary key.
            sbom_path: Path to the SBOM file on disk.
            dependency_status: Not used by this plugin.
            context: Optional SBOMContext with pre-computed metadata.
                When sha256_hash is available, it's compared against
                the computed hash to verify integrity.

        Returns:
            AssessmentResult with integrity verification finding:
            - "pass" if computed hash matches stored hash
            - "fail" if hashes differ (potential corruption/tampering)
            - "warning" if no stored hash available for comparison
        """
        # Always compute hash from file content
        data = sbom_path.read_bytes()
        computed_hash = hashlib.sha256(data).hexdigest()
        size_bytes = len(data)

        # Get stored hash from context
        stored_hash = context.sha256_hash if context else None

        # Determine verification result
        if stored_hash:
            if computed_hash == stored_hash:
                # Hashes match - integrity verified
                finding = Finding(
                    id="checksum:integrity-verified",
                    title="SBOM Integrity Verified",
                    description="SHA256 hash matches stored value - content has not been modified",
                    status="pass",
                    severity="info",
                    metadata={
                        "algorithm": "sha256",
                        "computed_hash": computed_hash,
                        "stored_hash": stored_hash,
                        "size_bytes": size_bytes,
                    },
                )
                summary = AssessmentSummary(
                    total_findings=1,
                    pass_count=1,
                    fail_count=0,
                    warning_count=0,
                    error_count=0,
                )
            else:
                # Hashes differ - potential tampering or corruption
                finding = Finding(
                    id="checksum:integrity-failed",
                    title="SBOM Integrity Check Failed",
                    description=(
                        f"SHA256 hash mismatch detected. "
                        f"Expected: {stored_hash[:16]}... "
                        f"Got: {computed_hash[:16]}... "
                        "This may indicate file corruption or unauthorized modification."
                    ),
                    status="fail",
                    severity="critical",
                    metadata={
                        "algorithm": "sha256",
                        "computed_hash": computed_hash,
                        "stored_hash": stored_hash,
                        "size_bytes": size_bytes,
                    },
                )
                summary = AssessmentSummary(
                    total_findings=1,
                    pass_count=0,
                    fail_count=1,
                    warning_count=0,
                    error_count=0,
                )
        else:
            # No stored hash available (legacy SBOM)
            finding = Finding(
                id="checksum:no-stored-hash",
                title="No Stored Hash Available",
                description=(
                    f"Cannot verify integrity - no stored hash found in database. "
                    f"Computed SHA256: {computed_hash}. "
                    "This SBOM may have been uploaded before hash tracking was enabled."
                ),
                status="warning",
                severity="medium",
                metadata={
                    "algorithm": "sha256",
                    "computed_hash": computed_hash,
                    "stored_hash": None,
                    "size_bytes": size_bytes,
                },
            )
            summary = AssessmentSummary(
                total_findings=1,
                pass_count=0,
                fail_count=0,
                warning_count=1,
                error_count=0,
            )

        # Create and return the result
        return AssessmentResult(
            plugin_name="checksum",
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=[finding],
            metadata={
                "sbom_id": sbom_id,
                "file_path": str(sbom_path),
                "verification_performed": stored_hash is not None,
            },
        )

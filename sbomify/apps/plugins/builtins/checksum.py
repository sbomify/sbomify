"""Checksum plugin for E2E validation of the plugin framework.

This is a minimal plugin that computes the SHA256 checksum of SBOM content.
It serves as a validation tool for testing the plugin framework end-to-end.
"""

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sbomify.apps.plugins.sdk.base import AssessmentPlugin
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.plugins.sdk.results import (
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
)


class ChecksumPlugin(AssessmentPlugin):
    """Dummy plugin that returns SBOM checksum for E2E validation.

    This plugin computes the SHA256 checksum of the SBOM content and returns
    it as a finding. It's primarily used for testing the plugin framework
    to ensure the end-to-end flow works correctly.

    The plugin always produces a single "pass" finding containing the checksum,
    making it useful for verifying that:
    - SBOMs are correctly fetched from storage
    - Plugins receive valid file paths
    - Results are correctly stored in AssessmentRun records

    Example:
        >>> plugin = ChecksumPlugin()
        >>> result = plugin.assess("sbom123", Path("/tmp/sbom.json"))
        >>> print(result.findings[0].description)
        'SHA256: a1b2c3d4...'
    """

    VERSION = "1.0.0"

    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata.

        Returns:
            PluginMetadata with name "checksum", version "1.0.0",
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
    ) -> AssessmentResult:
        """Compute SHA256 checksum of the SBOM content.

        Args:
            sbom_id: The SBOM's primary key (not used in this plugin).
            sbom_path: Path to the SBOM file on disk.
            dependency_status: Not used by this plugin.

        Returns:
            AssessmentResult with a single finding containing the checksum.
        """
        # Read the SBOM content and compute checksum
        data = sbom_path.read_bytes()
        checksum = hashlib.sha256(data).hexdigest()

        # Create the finding
        finding = Finding(
            id="checksum:sha256",
            title="SBOM Content Checksum",
            description=f"SHA256: {checksum}",
            status="pass",
            severity="info",
            metadata={
                "algorithm": "sha256",
                "digest": checksum,
                "size_bytes": len(data),
            },
        )

        # Create the summary
        summary = AssessmentSummary(
            total_findings=1,
            pass_count=1,
            fail_count=0,
            warning_count=0,
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
            },
        )

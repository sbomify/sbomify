"""Post-quantum (PQC) readiness assessment plugin for CycloneDX CBOM artifacts.

Adapts the pure crypto-inventory derivation + PQC classifier (in the ``sboms``
app) to the ADR-003 assessment framework: it reads the immutable artifact the
orchestrator hands it, derives the cryptographic-asset inventory, classifies
each asset's post-quantum readiness, and emits one compliance Finding per asset.

Runs on ``supported_bom_types=["cbom", "sbom"]``: pure CBOMs and ordinary
software SBOMs with embedded crypto assets both get a PQC verdict (mixed
documents keep ``bom_type=sbom`` so they retain NTIA and vulnerability
assessment). A document with no crypto assets returns a result flagged
``metadata={"skipped": True}`` so crypto-free SBOMs don't accumulate warning
findings. Results persist as immutable ``AssessmentRun`` records and render in
the existing compliance card.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sbomify.apps.plugins.builtins._crypto_assessment import summarize
from sbomify.apps.plugins.sdk import (
    AssessmentCategory,
    AssessmentPlugin,
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
    ScanMode,
)
from sbomify.apps.plugins.sdk.base import SBOMContext
from sbomify.apps.sboms.crypto_inventory import certificate_expiry_summary, derive_crypto_inventory
from sbomify.apps.sboms.pqc import PqcResult, PqcStatus, assess_inventory

logger = logging.getLogger(__name__)

_PLUGIN_NAME = "pqc-readiness"

# PQC verdict -> (compliance Finding.status, cosmetic severity). Compliance findings
# key off status; severity is only cosmetic.
_VERDICT = {
    PqcStatus.SAFE: ("pass", "info"),
    PqcStatus.VULNERABLE: ("fail", "high"),
    PqcStatus.REVIEW: ("warning", "medium"),
    PqcStatus.UNKNOWN: ("warning", "medium"),
}

_LABELS = {
    PqcStatus.SAFE: "Quantum-safe",
    PqcStatus.VULNERABLE: "Quantum-vulnerable",
    PqcStatus.REVIEW: "Needs review",
    PqcStatus.UNKNOWN: "Unrecognized algorithm",
}
_REMEDIATION = {
    PqcStatus.VULNERABLE: (
        "Migrate to a NIST-standardized post-quantum algorithm: ML-KEM (FIPS 203) for key establishment, "
        "ML-DSA (FIPS 204) or SLH-DSA (FIPS 205) for signatures."
    ),
    PqcStatus.REVIEW: (
        "Review against your cryptographic policy (e.g. NSA CNSA 2.0): confirm key size, standardization status, "
        "and intended use before relying on this algorithm."
    ),
    PqcStatus.UNKNOWN: "Could not classify this algorithm automatically; verify its post-quantum status manually.",
}


class PqcReadinessPlugin(AssessmentPlugin):
    """Classify a CBOM's cryptographic assets for post-quantum readiness."""

    VERSION = "1.0.0"
    STANDARD_NAME = "NIST Post-Quantum Cryptography Migration"
    STANDARD_VERSION = "NIST IR 8547"
    STANDARD_URL = "https://csrc.nist.gov/pubs/ir/8547/ipd"

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name=_PLUGIN_NAME,
            version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE,
            scan_mode=ScanMode.ONE_SHOT,
            supported_bom_types=["cbom", "sbom"],
            requires_crypto_assets=True,
        )

    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict[str, Any] | None = None,
        context: SBOMContext | None = None,
    ) -> AssessmentResult:
        try:
            document = json.loads(sbom_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
            return self._error_result(f"Invalid JSON: {exc}")
        except OSError as exc:  # pragma: no cover - defensive
            return self._error_result(f"Failed to read SBOM: {exc}")

        if not isinstance(document, dict):
            return self._error_result("SBOM is not a JSON object")

        inventory = derive_crypto_inventory(document)
        summary = assess_inventory(inventory)
        findings = [self._finding(index, result) for index, result in enumerate(summary.results)]
        metadata: dict[str, Any] = {
            "standard_name": self.STANDARD_NAME,
            "standard_version": self.STANDARD_VERSION,
            "standard_url": self.STANDARD_URL,
            "pqc_overall": summary.overall,
        }
        certificates = certificate_expiry_summary(inventory)
        if certificates:
            metadata["certificates"] = certificates
        if not findings:
            # A crypto-free ordinary SBOM is "nothing to assess" (most SBOMs
            # carry no crypto), so it skips quietly. An artifact explicitly
            # tagged cbom that declares zero crypto assets is a generator
            # misfire and must stay visible as a warning. The bom_type comes
            # from the orchestrator-provided context; plugins do not query
            # the database.
            if context is not None and context.bom_type == "cbom":
                findings = [
                    Finding(
                        id=f"{_PLUGIN_NAME}:no-assets",
                        title="No cryptographic assets found",
                        description=("This CBOM declares no crypto-asset components; the generator may have misfired."),
                        status="warning",
                        severity="medium",
                    )
                ]
            else:
                findings = [
                    Finding(
                        id=f"{_PLUGIN_NAME}:no-assets",
                        title="No cryptographic assets found",
                        description="This document declares no crypto-asset components; nothing to assess.",
                        status="info",
                        severity="info",
                    )
                ]
                metadata["skipped"] = True

        return AssessmentResult(
            plugin_name=_PLUGIN_NAME,
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summarize(findings),
            findings=findings,
            metadata=metadata,
        )

    def _finding(self, index: int, result: PqcResult) -> Finding:
        asset, verdict = result.asset, result.assessment
        name = asset.name or "Unnamed asset"
        finding_id = f"{_PLUGIN_NAME}:{asset.bom_ref or asset.name or f'asset-{index}'}"

        # A non-algorithm asset (certificate / protocol / related material) that the classifier
        # could not grade is "not assessed" — it is not an "unrecognized algorithm", so don't give
        # it an algorithm label or algorithm remediation.
        if verdict.status is PqcStatus.UNKNOWN and asset.asset_type is not None and asset.asset_type != "algorithm":
            kind = asset.asset_type.replace("-", " ")
            return Finding(
                id=finding_id,
                title=f"{name}: {kind} (not assessed)",
                description=f"{kind.capitalize()} assets are not assessed for post-quantum readiness by this check.",
                status="info",
                severity="info",
                metadata={"pqc_status": verdict.status.value, "asset_type": asset.asset_type, "asset_name": asset.name},
            )

        status, severity = _VERDICT.get(verdict.status, ("warning", "medium"))
        description = verdict.reason
        if verdict.data_quality_flag:
            description = f"{description}. {verdict.data_quality_flag}"
        return Finding(
            id=finding_id,
            title=f"{name}: {_LABELS.get(verdict.status, 'Unknown')}",
            description=description,
            status=status,
            severity=severity,
            remediation=_REMEDIATION.get(verdict.status),
            metadata={"pqc_status": verdict.status.value, "asset_type": asset.asset_type, "asset_name": asset.name},
        )

    def _error_result(self, message: str) -> AssessmentResult:
        return AssessmentResult(
            plugin_name=_PLUGIN_NAME,
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=AssessmentSummary(total_findings=1, error_count=1),
            findings=[
                Finding(
                    id=f"{_PLUGIN_NAME}:error",
                    title="PQC assessment error",
                    description=message,
                    status="error",
                    severity="high",
                )
            ],
            metadata={"error": True},
        )

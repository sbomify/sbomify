"""Certificate lifecycle assessment plugin.

Emits one finding per certificate asset in the derived crypto inventory:
expired certificates fail, certificates inside the renewal window or with an
over-long validity span warn, healthy certificates pass. The pqc-readiness
plugin keeps its aggregate ``certificates`` metadata block for the workspace
fleet rollup; this plugin adds the per-certificate findings that block cannot
express.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sbomify.apps.plugins.sdk import Finding
from sbomify.apps.sboms.crypto_inventory import (
    CERT_EXPIRING_SOON_DAYS,
    CryptoAsset,
    CryptoInventory,
    cert_expiry_state,
    parse_cert_datetime,
)

from ._crypto_assessment import CryptoInventoryPlugin

_PLUGIN_NAME = "certificate-lifecycle"

# CA/Browser Forum validity ceiling for publicly trusted TLS certificates:
# 398 days historically, 200 days for certificates issued on or after
# 2026-03-15 (ballot SC-081; drops again in later phases).
_SC081_CUTOVER = datetime(2026, 3, 15, tzinfo=timezone.utc)


def _max_validity_days(not_before: datetime | None) -> int:
    if not_before is not None and not_before >= _SC081_CUTOVER:
        return 200
    return 398


class CertificateLifecyclePlugin(CryptoInventoryPlugin):
    """Grade each certificate asset's expiry and validity window."""

    PLUGIN_NAME = _PLUGIN_NAME
    VERSION = "1.0.0"
    STANDARD_NAME = "Certificate Lifecycle"
    STANDARD_VERSION = "CA/Browser Forum baseline (SC-081 phased ceilings)"
    STANDARD_URL = "https://cabforum.org/baseline-requirements-documents/"
    ERROR_TITLE = "Certificate lifecycle assessment error"
    EMPTY_DESCRIPTION = "This document declares no certificate assets; nothing to assess."

    def build_findings(self, inventory: CryptoInventory, sbom_id: str) -> list[Finding]:
        certificates = [a for a in inventory.assets if a.asset_type == "certificate"]
        now = datetime.now(timezone.utc)
        return [self._finding(index, asset, now) for index, asset in enumerate(certificates)]

    def _finding(self, index: int, asset: CryptoAsset, now: datetime) -> Finding:
        certificate = asset.certificate or {}
        subject = certificate.get("subjectName") or asset.name or "Unnamed certificate"
        finding_id = f"{_PLUGIN_NAME}:{asset.bom_ref or asset.name or f'cert-{index}'}"
        base_metadata = {"asset_type": asset.asset_type, "asset_name": asset.name, "subject": subject}

        not_after_raw = certificate.get("notValidAfter")
        not_after = parse_cert_datetime(not_after_raw)
        if not_after is None:
            return Finding(
                id=finding_id,
                title=f"{subject}: Validity unknown",
                description="The certificate's notValidAfter date is missing or unparseable.",
                status="info",
                severity="info",
                metadata=base_metadata,
            )

        days, expired, expiring_soon = cert_expiry_state(not_after_raw, now)
        metadata = {**base_metadata, "not_valid_after": not_after.isoformat(), "days_to_expiry": days}
        if expired:
            return Finding(
                id=finding_id,
                title=f"{subject}: Expired",
                description=f"Certificate expired {abs(days or 0)} day(s) ago ({not_after.date().isoformat()}).",
                status="fail",
                severity="high",
                remediation="Renew and redeploy the certificate; expired certificates break trust chains.",
                metadata=metadata,
            )
        if expiring_soon:
            return Finding(
                id=finding_id,
                title=f"{subject}: Expiring soon",
                description=f"Certificate expires in {days} day(s), within the {CERT_EXPIRING_SOON_DAYS}-day window.",
                status="warning",
                severity="medium",
                remediation="Schedule renewal before the expiry date to avoid downtime.",
                metadata=metadata,
            )

        not_before = parse_cert_datetime(certificate.get("notValidBefore"))
        if not_before is not None:
            span = (not_after - not_before).days
            ceiling = _max_validity_days(not_before)
            if span > ceiling:
                return Finding(
                    id=finding_id,
                    title=f"{subject}: Long validity window",
                    description=(
                        f"Validity window of {span} days exceeds the {ceiling}-day CA/Browser Forum "
                        "ceiling for publicly trusted TLS certificates issued on this date."
                    ),
                    status="warning",
                    severity="low",
                    remediation="Reissue with a shorter validity window and rotate on a schedule.",
                    metadata={**metadata, "validity_days": span},
                )

        return Finding(
            id=finding_id,
            title=f"{subject}: Valid",
            description=f"Certificate is valid; expires in {days} day(s) ({not_after.date().isoformat()}).",
            status="pass",
            severity="info",
            metadata=metadata,
        )

"""SBOM Verification plugin for signature and provenance checking.

This plugin performs a comprehensive verification suite on SBOMs:
1. Re-computes SHA-256 and compares to the stored digest
2. Checks whether a cryptographic signature is attached
3. Validates the signature (best-effort, cosign-bundle via sigstore)
4. Checks whether a provenance attestation is attached
5. Verifies the provenance subject digest matches the SBOM hash
"""

import base64
import hashlib
import json
import logging
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

logger = logging.getLogger(__name__)


class SBOMVerificationPlugin(AssessmentPlugin):
    """SBOM signature and provenance verification plugin.

    Produces up to five findings covering digest integrity, signature
    presence/validity, and provenance presence/digest-match.
    """

    VERSION = "1.0.0"

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="sbom-verification",
            version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE,
            supported_bom_types=["sbom"],
        )

    def _fetch_blob(self, key: str) -> bytes | None:
        """Fetch a blob from S3. Separated for test-time mocking."""
        from sbomify.apps.core.object_store import S3Client

        s3 = S3Client("SBOMS")
        return s3.get_sbom_data(key)

    def _check_digest_integrity(
        self,
        sbom_data: bytes,
        context: SBOMContext | None,
    ) -> Finding:
        computed = hashlib.sha256(sbom_data).hexdigest()
        stored = context.sha256_hash if context else None

        if not stored:
            return Finding(
                id="verification:digest-integrity",
                title="No Stored Hash Available",
                description="Cannot verify digest integrity — no stored hash in context.",
                status="warning",
                severity="medium",
                metadata={"computed_hash": computed, "stored_hash": None},
            )

        if computed == stored:
            return Finding(
                id="verification:digest-integrity",
                title="Digest Integrity Verified",
                description="SHA-256 hash matches the stored value.",
                status="pass",
                severity="info",
                metadata={"computed_hash": computed, "stored_hash": stored},
            )

        return Finding(
            id="verification:digest-integrity",
            title="Digest Integrity Failed",
            description=(f"SHA-256 mismatch. Expected {stored[:16]}... got {computed[:16]}..."),
            status="fail",
            severity="critical",
            metadata={"computed_hash": computed, "stored_hash": stored},
        )

    def _check_signature_present(self, context: SBOMContext | None) -> Finding:
        if context and context.signature_blob_key:
            return Finding(
                id="verification:signature-present",
                title="Signature Attached",
                description="A cryptographic signature is attached to this SBOM.",
                status="pass",
                severity="info",
                metadata={"signature_blob_key": context.signature_blob_key},
            )
        return Finding(
            id="verification:signature-present",
            title="No Signature Attached",
            description="No cryptographic signature is attached to this SBOM.",
            status="warning",
            severity="medium",
            metadata={},
        )

    def _check_signature_valid(self, sbom_data: bytes, context: SBOMContext | None) -> Finding:
        if not context or not context.signature_blob_key:
            return Finding(
                id="verification:signature-valid",
                title="Signature Validation Skipped",
                description="No signature to validate.",
                status="warning",
                severity="low",
                metadata={},
            )

        sig_type = context.signature_type or "unknown"

        blob = self._fetch_blob(context.signature_blob_key)
        if blob is None:
            return Finding(
                id="verification:signature-valid",
                title="Signature Blob Missing",
                description="Signature key is set but the blob could not be retrieved from storage.",
                status="fail",
                severity="high",
                metadata={"signature_blob_key": context.signature_blob_key},
            )

        if sig_type == "cosign-bundle":
            return self._verify_cosign_bundle(blob, sbom_data)

        return Finding(
            id="verification:signature-valid",
            title="Unsupported Signature Type",
            description=f"Signature type '{sig_type}' is not yet supported for validation.",
            status="warning",
            severity="low",
            metadata={"signature_type": sig_type},
        )

    def _verify_cosign_bundle(self, bundle_bytes: bytes, sbom_data: bytes) -> Finding:
        """Verify a Cosign/Sigstore bundle against the SBOM content.

        Note: Uses UnsafeNoOp policy which verifies the signature is
        cryptographically valid but does NOT check signer identity.
        A proper identity policy should be configured per-deployment.
        """
        try:
            from sigstore.models import Bundle
            from sigstore.verify import Verifier
            from sigstore.verify.policy import UnsafeNoOp

            verifier = Verifier.production()
            bundle = Bundle.from_json(bundle_bytes)
            verifier.verify_artifact(
                input_=sbom_data,
                bundle=bundle,
                policy=UnsafeNoOp(),
            )
            return Finding(
                id="verification:signature-valid",
                title="Cosign Signature Cryptographically Valid",
                description=(
                    "Cosign bundle signature is cryptographically valid. "
                    "Note: signer identity was not verified (no identity policy configured)."
                ),
                status="pass",
                severity="info",
                metadata={"signature_type": "cosign-bundle", "identity_verified": False},
            )
        except ImportError:
            return Finding(
                id="verification:signature-valid",
                title="Sigstore Library Not Available",
                description="The sigstore library is not installed — cannot verify cosign bundle.",
                status="warning",
                severity="low",
                metadata={"signature_type": "cosign-bundle"},
            )
        except Exception as exc:
            return Finding(
                id="verification:signature-valid",
                title="Cosign Signature Verification Failed",
                description=f"Cosign bundle verification failed: {exc}",
                status="fail",
                severity="high",
                metadata={"signature_type": "cosign-bundle", "error": str(exc)},
            )

    def _check_provenance_present(self, context: SBOMContext | None) -> Finding:
        if context and context.provenance_blob_key:
            return Finding(
                id="verification:provenance-present",
                title="Provenance Attached",
                description="A provenance attestation is attached to this SBOM.",
                status="pass",
                severity="info",
                metadata={"provenance_blob_key": context.provenance_blob_key},
            )
        return Finding(
            id="verification:provenance-present",
            title="No Provenance Attached",
            description="No provenance attestation is attached to this SBOM.",
            status="warning",
            severity="medium",
            metadata={},
        )

    def _check_provenance_digest(self, context: SBOMContext | None) -> Finding:
        if not context or not context.provenance_blob_key:
            return Finding(
                id="verification:provenance-digest",
                title="Provenance Digest Check Skipped",
                description="No provenance attestation to check.",
                status="warning",
                severity="low",
                metadata={},
            )

        blob = self._fetch_blob(context.provenance_blob_key)
        if blob is None:
            return Finding(
                id="verification:provenance-digest",
                title="Provenance Blob Missing",
                description="Provenance key is set but the blob could not be retrieved from storage.",
                status="fail",
                severity="high",
                metadata={"provenance_blob_key": context.provenance_blob_key},
            )

        return self._verify_provenance_subjects(blob, context.sha256_hash)

    def _verify_provenance_subjects(
        self,
        blob: bytes,
        expected_hash: str | None,
    ) -> Finding:
        """Parse a provenance attestation and check subject digests.

        Supports:
        - Direct in-toto Statement (``_type`` == ``https://in-toto.io/Statement/...``)
        - DSSE envelope wrapping a Statement (``payloadType`` present, base64
          payload)
        """
        try:
            data = json.loads(blob)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return Finding(
                id="verification:provenance-digest",
                title="Provenance Parse Error",
                description=f"Could not parse provenance JSON: {exc}",
                status="fail",
                severity="high",
                metadata={"error": str(exc)},
            )

        statement = self._extract_statement(data)
        if statement is None:
            return Finding(
                id="verification:provenance-digest",
                title="Provenance Format Unrecognised",
                description="Provenance payload is neither a DSSE envelope nor an in-toto Statement.",
                status="fail",
                severity="high",
                metadata={},
            )

        subjects: list[dict[str, Any]] = statement.get("subject", [])
        if not subjects:
            return Finding(
                id="verification:provenance-digest",
                title="No Subjects in Provenance",
                description="The provenance statement contains no subject entries.",
                status="fail",
                severity="high",
                metadata={},
            )

        if not expected_hash:
            return Finding(
                id="verification:provenance-digest",
                title="Cannot Compare — No Stored Hash",
                description="Provenance subjects found but no stored SHA-256 hash to compare against.",
                status="warning",
                severity="medium",
                metadata={"subjects_count": len(subjects)},
            )

        for subj in subjects:
            if not isinstance(subj, dict):
                continue
            digest = subj.get("digest")
            digest_sha256 = digest.get("sha256") if isinstance(digest, dict) else None
            if digest_sha256 == expected_hash:
                return Finding(
                    id="verification:provenance-digest",
                    title="Provenance Digest Matches",
                    description="A provenance subject SHA-256 digest matches the stored SBOM hash.",
                    status="pass",
                    severity="info",
                    metadata={
                        "matched_subject": subj.get("name"),
                        "digest": digest_sha256,
                    },
                )

        return Finding(
            id="verification:provenance-digest",
            title="Provenance Digest Mismatch",
            description="No provenance subject SHA-256 digest matches the stored SBOM hash.",
            status="fail",
            severity="high",
            metadata={
                "expected_hash": expected_hash,
                "subject_digests": [(s.get("digest") or {}).get("sha256") for s in subjects if isinstance(s, dict)],
            },
        )

    @staticmethod
    def _extract_statement(data: Any) -> dict[str, Any] | None:
        """Return the in-toto Statement dict, unwrapping DSSE if needed."""
        if not isinstance(data, dict):
            return None

        if "_type" in data and "subject" in data:
            return data

        if "payloadType" in data and "payload" in data:
            payload = data["payload"]
            if not isinstance(payload, (str, bytes, bytearray)):
                return None
            try:
                raw = base64.b64decode(payload, validate=True)
                statement = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
                return None
            if not isinstance(statement, dict):
                return None
            return statement

        return None

    # ------------------------------------------------------------------
    # Main assess entry-point
    # ------------------------------------------------------------------

    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict[str, Any] | None = None,
        context: SBOMContext | None = None,
    ) -> AssessmentResult:
        sbom_data = sbom_path.read_bytes()
        findings: list[Finding] = [
            self._check_digest_integrity(sbom_data, context),
            self._check_signature_present(context),
            self._check_signature_valid(sbom_data, context),
            self._check_provenance_present(context),
            self._check_provenance_digest(context),
        ]

        pass_count = sum(1 for f in findings if f.status == "pass")
        fail_count = sum(1 for f in findings if f.status == "fail")
        warning_count = sum(1 for f in findings if f.status == "warning")

        summary = AssessmentSummary(
            total_findings=len(findings),
            pass_count=pass_count,
            fail_count=fail_count,
            warning_count=warning_count,
            error_count=0,
        )

        return AssessmentResult(
            plugin_name="sbom-verification",
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=findings,
            metadata={
                "sbom_id": sbom_id,
                "file_path": str(sbom_path),
            },
        )

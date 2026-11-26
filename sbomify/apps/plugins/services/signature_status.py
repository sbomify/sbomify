"""Whether an SBOM's stored signature has been verified, for its header chip.

The upload endpoint stores any bytes it is given as the signature, so having
one says nothing about whether it holds. The verification plugin's
``verification:signature-valid`` finding does, and the chip reads that rather
than the presence of the file.
"""

from __future__ import annotations

from dataclasses import dataclass

from sbomify.apps.core.services.results import ServiceResult
from sbomify.logging import getLogger

from ..models import AssessmentRun
from ..result_store import load_result
from ..sdk.enums import RunStatus

logger = getLogger(__name__)

PLUGIN_NAME = "sbom-verification"
FINDING_ID = "verification:signature-valid"


@dataclass(frozen=True)
class SignatureStatus:
    #: ``verified``, ``failed``, ``checking`` or ``unverified``.
    state: str
    signer: str = ""
    issuer: str = ""

    @property
    def signed_by(self) -> str:
        signed_by = f"Signed by {self.signer or 'an unknown identity'}"
        return f"{signed_by} ({self.issuer})" if self.issuer else signed_by


def get_signature_status(sbom_id: str) -> ServiceResult[SignatureStatus]:
    runs = AssessmentRun.objects.filter(sbom_id=sbom_id, plugin_name=PLUGIN_NAME).order_by("-created_at")
    latest = runs.only("id", "status").first()
    if latest is None:
        return ServiceResult.success(SignatureStatus("unverified"))
    if latest.status in (RunStatus.PENDING.value, RunStatus.RUNNING.value):
        return ServiceResult.success(SignatureStatus("checking"))

    completed = runs.filter(status=RunStatus.COMPLETED.value).first()
    if completed is None:
        return ServiceResult.success(SignatureStatus("unverified"))
    try:
        result = load_result(completed) or {}
    except Exception:
        logger.exception("Could not read verification result %s for SBOM %s", completed.id, sbom_id)
        return ServiceResult.failure("Could not read the signature check")

    finding = next((f for f in result.get("findings", []) if f.get("id") == FINDING_ID), None)
    if finding is None:
        return ServiceResult.success(SignatureStatus("unverified"))
    metadata = finding.get("metadata") or {}
    state = {"pass": "verified", "fail": "failed"}.get(finding.get("status", ""), "unverified")
    return ServiceResult.success(
        SignatureStatus(state, signer=metadata.get("identity", ""), issuer=metadata.get("issuer", ""))
    )

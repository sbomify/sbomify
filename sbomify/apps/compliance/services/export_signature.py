"""The manufacturer's Sigstore signature over a CRA export bundle.

sbomify holds no signing key. The manufacturer signs the exported ZIP keyless
with ``cosign sign-blob --bundle``, as a person or as a CI workflow, and uploads
the bundle cosign writes. It is verified here against the identity and OIDC
issuer they name, the way ``cosign verify-blob`` would, and kept beside the ZIP,
which stays exactly as exported.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from django.conf import settings as django_settings
from django.db import transaction
from sigstore.errors import NetworkError, TUFError, VerificationError
from sigstore.hashes import Hashed
from sigstore.models import Bundle, InvalidBundle
from sigstore.verify import Verifier
from sigstore.verify.policy import Identity
from sigstore_models.common.v1 import HashAlgorithm

from sbomify.apps.compliance import audit
from sbomify.apps.compliance.models import CRAExportPackage
from sbomify.apps.compliance.services.export_service import signature_storage_key
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.core.services.results import ServiceResult

if TYPE_CHECKING:
    from sbomify.apps.core.models import User

logger = logging.getLogger(__name__)

# A keyless bundle is a certificate, a signature and a log entry: about 6 KB.
MAX_BUNDLE_BYTES = 64 * 1024


def _verifier() -> Verifier:
    """Sigstore's public-good instance, its trust root refreshed over TUF."""
    return Verifier.production()


def sign_export(
    package: CRAExportPackage,
    *,
    bundle: dict[str, Any],
    identity: str,
    issuer: str,
    user: User | None,
) -> ServiceResult[CRAExportPackage]:
    """Verify ``bundle`` as a signature over ``package``'s ZIP by ``identity`` through ``issuer``, then keep it."""
    identity, issuer = identity.strip(), issuer.strip()
    if package.signed_by:
        return ServiceResult.failure("This bundle is already signed.", status_code=409)

    raw = json.dumps(bundle).encode()
    if len(raw) > MAX_BUNDLE_BYTES:
        return ServiceResult.failure("The signature file is larger than 64 KB.", status_code=400)
    try:
        sigstore_bundle = Bundle.from_json(raw)
    except InvalidBundle:
        return ServiceResult.failure(
            "This file is not a Sigstore bundle. Sign with cosign 3 or later, which writes one with --bundle.",
            status_code=400,
        )

    try:
        _verifier().verify_artifact(
            input_=Hashed(algorithm=HashAlgorithm.SHA2_256, digest=bytes.fromhex(package.content_hash)),
            bundle=sigstore_bundle,
            policy=Identity(identity=identity, issuer=issuer),
        )
    except VerificationError as exc:
        return ServiceResult.failure(
            f"The signature does not match this bundle, or was not made by {identity} through {issuer}: {exc}",
            status_code=400,
        )
    except (TUFError, NetworkError):
        logger.warning("Could not refresh the Sigstore trust root", exc_info=True)
        return ServiceResult.failure("Could not reach Sigstore to check the signature. Try again.", status_code=502)

    # Locked while the bundle is stored, so two uploads that both verified
    # cannot leave one signer's bundle in storage and the other's name here.
    with transaction.atomic():
        locked = CRAExportPackage.objects.select_for_update().get(pk=package.pk)
        if locked.signed_by:
            return ServiceResult.failure("This bundle is already signed.", status_code=409)
        try:
            StorageClient("DOCUMENTS").upload_data_as_file(
                django_settings.AWS_DOCUMENTS_STORAGE_BUCKET_NAME, signature_storage_key(locked), raw
            )
        except Exception:
            logger.exception("Failed to store the export signature")
            return ServiceResult.failure("Failed to store the signature.", status_code=502)
        locked.signed_by = identity
        locked.signed_by_issuer = issuer
        locked.signed_at = sigstore_bundle.signing_certificate.not_valid_before_utc
        locked.save(update_fields=["signed_by", "signed_by_issuer", "signed_at"])

    audit.log_export_signed(
        user=user,
        assessment_id=locked.assessment_id,
        team_id=package.assessment.team_id,
        package_id=locked.id,
        content_hash=locked.content_hash,
        signed_by=identity,
        issuer=issuer,
    )
    return ServiceResult.success(locked)

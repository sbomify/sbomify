"""SBOM Verification plugin for signature, provenance, and attestation checking.

This plugin unifies the previously-separate ``github-attestation`` and
``sbom-verification`` plugins into a single attestation-category check that
runs every available verification source in one pass:

1. Re-computes SHA-256 and compares to the stored digest.
2. Checks whether a sbomify-stored cryptographic signature is attached
   (cosign-bundle via the ``signature_blob_key`` on the SBOM row).
3. Validates the stored signature: a Sigstore bundle with the ``sigstore``
   library (``Verifier.production().verify_artifact``), an older cosign
   bundle with ``cosign verify-blob``. The signer is reported, not judged.
4. Checks whether a sbomify-stored provenance attestation is attached
   and verifies its subject digest matches the SBOM hash.
5. If the SBOM declares a GitHub VCS link, fetches the GitHub Sigstore
   attestation bundle from the public Attestations API and verifies it
   with ``cosign verify-blob-attestation``. A missing attestation is only
   retried while no stored source has verified the SBOM; after one has, it
   is recorded as an ``info`` note instead.
6. Emits an aggregating ``verification:attestation`` summary finding
   whose status is ``pass`` when *any* cryptographic source verified
   and ``fail`` when none did. This is the signal BSI consumes via
   ``requires_one_of: [{"type": "category", "value": "attestation"}]`` —
   a digest-only "pass" must NOT satisfy the attestation requirement.

The plugin is in the ``attestation`` category so a single ``requires_one_of``
clause in BSI / FDA / etc. can match either a sbomify-stored signature
or a GitHub-published attestation.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings

from sbomify.apps.plugins.builtins._spdx3_helpers import is_spdx3
from sbomify.apps.plugins.sdk.base import AssessmentPlugin, RetryLaterError, SBOMContext
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, ScanMode
from sbomify.apps.plugins.sdk.results import (
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
)
from sbomify.apps.plugins.utils import get_http_session
from sbomify.apps.sboms.provenance import (
    ProvenanceFormatError,
    matching_subject,
    parse_statements,
    subject_digests,
)

logger = logging.getLogger(__name__)


class AttestationNotYetAvailableError(RetryLaterError):
    """Raised when GitHub returns 404 because the attestation isn't published yet.

    GitHub's attestation pipeline is asynchronous — a ``404`` immediately
    after a workflow run does not mean the attestation will never exist.
    Inheriting from ``RetryLaterError`` signals the task layer to schedule
    a retry rather than mark the run failed.
    """


class GitHubRateLimitedError(RetryLaterError):
    """Raised when GitHub refuses the lookup because its API rate limit was hit.

    The limit resets within the hour, so the attestation is still there to be
    found. Treating the refusal as final failed SBOMs whose attestations were
    fine, simply because their release uploaded more SBOMs than the remaining
    quota allowed.
    """


class SBOMVerificationPlugin(AssessmentPlugin):
    """Unified SBOM signature, provenance, and attestation verification plugin.

    Produces up to seven findings. The first six are evidence sub-checks;
    the seventh ``verification:attestation`` is the consolidated pass/fail
    that drives ``_is_passing`` for upstream consumers (BSI, FDA, etc.).
    """

    VERSION = "2.1.0"

    # Stored sources that can verify an SBOM without GitHub.
    _CRYPTO_FINDING_IDS = frozenset({"verification:signature-valid", "verification:provenance-digest"})

    DEFAULT_TIMEOUT = 60
    DEFAULT_CERTIFICATE_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
    # cosign v3 strictly validates --type against the predicate type when
    # --new-bundle-format is active (default in v3). actions/attest-build-provenance
    # emits https://slsa.dev/provenance/v1, which cosign aliases to "slsaprovenance1".
    GITHUB_ATTESTATION_PREDICATE_TYPE = "slsaprovenance1"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        # The plugin config UI doesn't enforce field types, so a saved
        # team-level value could be a string or anything else. Coerce
        # defensively and fall back to the default rather than failing
        # plugin instantiation on a bad config blob.
        raw_timeout = self.config.get("timeout", self.DEFAULT_TIMEOUT)
        try:
            self.timeout = int(raw_timeout)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid timeout config %r; falling back to default %s seconds",
                raw_timeout,
                self.DEFAULT_TIMEOUT,
            )
            self.timeout = self.DEFAULT_TIMEOUT
        self.certificate_oidc_issuer = self.config.get(
            "certificate_oidc_issuer",
            self.DEFAULT_CERTIFICATE_OIDC_ISSUER,
        )

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="sbom-verification",
            version=self.VERSION,
            category=AssessmentCategory.ATTESTATION,
            # GitHub's attestation pipeline is asynchronous — a 404 on the
            # public Attestations API immediately after a workflow run can
            # mean "not yet published" rather than "doesn't exist". The
            # github-attestation flow raises ``RetryLaterError`` (via the
            # ``AttestationNotYetAvailableError`` subclass) on 404, which
            # is the contract for ``ScanMode.CONTINUOUS``.
            scan_mode=ScanMode.CONTINUOUS,
            supported_bom_types=["sbom"],
        )

    # ------------------------------------------------------------------
    # Storage hook (separated for test-time mocking)
    # ------------------------------------------------------------------

    def _fetch_blob(self, key: str) -> bytes | None:
        from sbomify.apps.core.object_store import StorageClient

        s3 = StorageClient("SBOMS")
        return s3.get_sbom_data(key)

    # ------------------------------------------------------------------
    # 1. Digest integrity
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # 2. Stored-signature presence + validity
    # ------------------------------------------------------------------

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
        """Verify a Sigstore bundle against the SBOM content.

        Two formats reach this. ``cosign`` v3 writes the Sigstore bundle
        (``mediaType``, ``verificationMaterial``), which the ``sigstore``
        library verifies in process. ``cosign`` v2, and v3 with
        ``--new-bundle-format=false``, writes the older cosign bundle
        (``base64Signature``, ``cert``, ``rekorBundle``), which the library
        cannot load, so that one goes to the ``cosign`` binary.

        Either way the signature, certificate chain and transparency log entry
        are checked, and the signer is reported. Which signer is acceptable is
        not decided here: there is no identity policy to check it against.
        """
        try:
            document = json.loads(bundle_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            document = None
        if not isinstance(document, dict):
            return self._signature_finding(
                "fail", "Signature Is Not a Sigstore Bundle", "The signature file is not a JSON Sigstore bundle."
            )

        if "mediaType" in document:
            return self._verify_sigstore_bundle(bundle_bytes, sbom_data)
        if "base64Signature" in document:
            return self._verify_legacy_cosign_bundle(document, bundle_bytes, sbom_data)
        return self._signature_finding(
            "fail",
            "Signature Is Not a Sigstore Bundle",
            "The signature file is JSON, but neither a Sigstore bundle nor a cosign bundle.",
        )

    @staticmethod
    def _signature_finding(
        status: str, title: str, description: str, metadata: dict[str, Any] | None = None
    ) -> Finding:
        return Finding(
            id="verification:signature-valid",
            title=title,
            description=description,
            status=status,
            severity="info" if status == "pass" else ("low" if status == "warning" else "high"),
            metadata={"signature_type": "cosign-bundle", **(metadata or {})},
        )

    def _signature_verified(self, identity: dict[str, str], bundle_format: str) -> Finding:
        signer = identity.get("identity") or "an unknown identity"
        issuer = identity.get("issuer")
        description = f"The signature over this SBOM is valid. Signed by {signer}"
        description += f" (issuer {issuer})." if issuer else "."
        description += " sbomify does not check which signers to trust, so confirm this is the one you expect."
        return self._signature_finding(
            "pass",
            "Cosign Signature Cryptographically Valid",
            description,
            {"bundle_format": bundle_format, "identity_verified": False, **identity},
        )

    @staticmethod
    def _short_error(exc: BaseException) -> str:
        message = str(exc).strip().splitlines()
        return (message[0] if message else type(exc).__name__)[:300]

    @staticmethod
    def _signer_identity(certificate: Any) -> dict[str, str]:
        """The subject and OIDC issuer a Fulcio certificate was issued for."""
        from cryptography import x509

        identity: dict[str, str] = {}
        try:
            names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            for kind in (x509.RFC822Name, x509.UniformResourceIdentifier, x509.OtherName):
                values = names.get_values_for_type(kind)
                if values:
                    value = values[0]
                    identity["identity"] = value if isinstance(value, str) else repr(value)
                    break
        except x509.ExtensionNotFound:
            pass

        # Fulcio records the issuer twice: 57264.1.8 as a DER UTF8String, and
        # the deprecated 57264.1.1 as raw bytes.
        for oid, der in (("1.3.6.1.4.1.57264.1.8", True), ("1.3.6.1.4.1.57264.1.1", False)):
            try:
                raw = certificate.extensions.get_extension_for_oid(x509.ObjectIdentifier(oid)).value.value
            except x509.ExtensionNotFound:
                continue
            if der and len(raw) > 2 and raw[0] == 0x0C:
                raw = raw[2:] if raw[1] < 0x80 else raw[2 + (raw[1] & 0x7F) :]
            identity["issuer"] = raw.decode("utf-8", "replace")
            break
        return identity

    def _verify_sigstore_bundle(self, bundle_bytes: bytes, sbom_data: bytes) -> Finding:
        try:
            from sigstore.models import Bundle
            from sigstore.verify import Verifier
            from sigstore.verify.policy import UnsafeNoOp
        except ImportError:
            return self._signature_finding(
                "warning",
                "Sigstore Library Not Available",
                "The sigstore library is not installed, so the bundle cannot be verified.",
            )

        try:
            bundle = Bundle.from_json(bundle_bytes)
            Verifier.production().verify_artifact(input_=sbom_data, bundle=bundle, policy=UnsafeNoOp())
        except Exception as exc:
            error = self._short_error(exc)
            return self._signature_finding(
                "fail",
                "Cosign Signature Verification Failed",
                f"Cosign bundle verification failed: {error}",
                {"bundle_format": "sigstore", "error": error},
            )
        return self._signature_verified(self._signer_identity(bundle.signing_certificate), "sigstore")

    def _verify_legacy_cosign_bundle(self, document: dict[str, Any], bundle_bytes: bytes, sbom_data: bytes) -> Finding:
        if not document.get("cert"):
            return self._signature_finding(
                "warning",
                "Key-Based Signature Not Verified",
                (
                    "This cosign bundle was signed with a key, not keylessly. sbomify has no public key to "
                    "check it against. Sign without --key to get a verifiable bundle."
                ),
                {"bundle_format": "cosign-legacy"},
            )

        cosign_path = shutil.which("cosign")
        if not cosign_path:
            return self._signature_finding(
                "warning",
                "Cosign Not Available",
                "This bundle uses the older cosign format, which needs the cosign binary, and it is not installed.",
                {"bundle_format": "cosign-legacy"},
            )

        with tempfile.TemporaryDirectory() as workdir:
            sbom_path = Path(workdir) / "sbom"
            bundle_path = Path(workdir) / "bundle.json"
            sbom_path.write_bytes(sbom_data)
            bundle_path.write_bytes(bundle_bytes)
            cmd = [
                cosign_path,
                "verify-blob",
                "--bundle",
                str(bundle_path),
                "--certificate-identity-regexp",
                ".*",
                "--certificate-oidc-issuer-regexp",
                ".*",
                str(sbom_path),
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                return self._signature_finding(
                    "warning",
                    "Cosign Signature Check Timed Out",
                    "cosign verify-blob did not finish in time. Run the assessment again.",
                    {"bundle_format": "cosign-legacy"},
                )
            except OSError as exc:
                return self._signature_finding(
                    "warning",
                    "Cosign Not Available",
                    f"Failed to launch cosign: {exc}",
                    {"bundle_format": "cosign-legacy"},
                )

        if result.returncode != 0:
            output = (result.stderr or result.stdout or "").strip().splitlines()
            error = (output[0] if output else f"cosign returned {result.returncode}")[:300]
            return self._signature_finding(
                "fail",
                "Cosign Signature Verification Failed",
                f"Cosign bundle verification failed: {error}",
                {"bundle_format": "cosign-legacy", "error": error},
            )

        identity: dict[str, str] = {}
        try:
            from cryptography import x509

            identity = self._signer_identity(x509.load_pem_x509_certificate(base64.b64decode(document["cert"])))
        except (ValueError, TypeError):
            logger.debug("Could not read the signer from a verified cosign bundle", exc_info=True)
        return self._signature_verified(identity, "cosign-legacy")

    # ------------------------------------------------------------------
    # 3. Stored-provenance presence + subject-digest match
    # ------------------------------------------------------------------

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
        Every shape ``sbomify.apps.sboms.provenance`` reads: a Statement, a
        DSSE envelope, a Sigstore bundle with a ``dsseEnvelope``, or JSONL of
        those.
        """
        try:
            statements = parse_statements(blob)
        except ProvenanceFormatError as exc:
            parse_failed = str(exc).startswith("Invalid JSON")
            return Finding(
                id="verification:provenance-digest",
                title="Provenance Parse Error" if parse_failed else "Provenance Format Unrecognised",
                description=(
                    f"Could not parse provenance JSON: {exc}"
                    if parse_failed
                    else "Provenance payload is neither a DSSE envelope, a Sigstore bundle nor an in-toto Statement."
                ),
                status="fail",
                severity="high",
                metadata={"error": str(exc)},
            )

        digests = subject_digests(statements)
        if not digests:
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
                metadata={"subjects_count": len(digests)},
            )

        if (subject := matching_subject(statements, expected_hash)) is not None:
            return Finding(
                id="verification:provenance-digest",
                title="Provenance Digest Matches",
                description="A provenance subject SHA-256 digest matches the stored SBOM hash.",
                status="pass",
                severity="info",
                metadata={"matched_subject": subject.get("name"), "digest": expected_hash},
            )

        return Finding(
            id="verification:provenance-digest",
            title="Provenance Digest Mismatch",
            description="No provenance subject SHA-256 digest matches the stored SBOM hash.",
            status="fail",
            severity="high",
            metadata={
                "expected_hash": expected_hash,
                "subject_digests": digests,
            },
        )

    # ------------------------------------------------------------------
    # 4. GitHub-published attestation (formerly the github-attestation plugin)
    # ------------------------------------------------------------------

    def _check_github_attestation(
        self,
        sbom_data: bytes,
        sbom_path: Path,
        sbom_dict: dict[str, Any] | None,
        context: SBOMContext | None,
    ) -> Finding:
        """Try to verify a GitHub-published Sigstore attestation for the SBOM.

        Logic:
        1. Extract VCS info (org/repo) from the SBOM. No VCS → skipped (warning).
        2. Compute or reuse SHA-256.
        3. Fetch the bundle from ``GET /repos/{org}/{repo}/attestations/sha256:{digest}``
           — public, no auth required. ``404`` raises
           ``AttestationNotYetAvailableError`` so the task layer schedules a retry.
        4. Run ``cosign verify-blob-attestation`` to validate.
        """
        if sbom_dict is None:
            return self._gha_finding(
                "warning",
                "GitHub Attestation Skipped",
                "SBOM could not be parsed; skipping GitHub attestation lookup.",
                metadata={"reason": "sbom_parse_failed"},
            )

        vcs_info = self._extract_vcs_info(sbom_dict)
        if not vcs_info:
            return self._gha_finding(
                "warning",
                "No GitHub VCS Information Found",
                (
                    "Could not find GitHub VCS information in the SBOM. "
                    "GitHub attestation lookup requires externalReferences with "
                    "type 'vcs' (CycloneDX) or referenceType 'vcs' (SPDX) pointing "
                    "to a GitHub repository."
                ),
                metadata={"reason": "no_vcs_info"},
            )

        github_org = vcs_info.get("org", "")
        github_repo = vcs_info.get("repo", "")
        # ``--certificate-identity-regexp`` interprets its argument as a
        # regex, so any metacharacters (``.``, ``+``, etc.) in the org or
        # repo would broaden the match and weaken identity verification.
        # Escape both segments when building the default pattern. An
        # explicit override in plugin config is left untouched — operators
        # who set a custom pattern are expected to know it's a regex.
        identity_regexp = self.config.get(
            "certificate_identity_regexp",
            rf"^https://github\.com/{re.escape(github_org)}/{re.escape(github_repo)}/.*",
        )

        precomputed = context.sha256_hash if context else None
        digest = precomputed or hashlib.sha256(sbom_data).hexdigest()

        # Qualified when the repository came from a dependency rather than from
        # the document's own subject. _extract_vcs_info falls back to the first
        # component carrying a VCS reference, which for a Python SBOM is
        # typically an upstream OSS project — naming it unqualified tells the
        # reader to go and fix a workflow in a repository they do not own.
        repo_provenance = "" if vcs_info.get("source") == "document" else " (from a package reference in the SBOM)"

        # Per-source failures below emit ``warning`` rather than ``fail`` so
        # they don't drive ``fail_count > 0`` on the run when another source
        # (stored signature/provenance) has already verified the SBOM. The
        # aggregating ``verification:attestation`` summary is the single
        # ``fail`` signal for "no source verified" — it's what BSI's
        # ``requires_one_of: attestation`` consumes.
        bundle = self._download_github_bundle(github_org, github_repo, digest, repo_provenance)
        if not bundle.get("success"):
            return self._gha_finding(
                "warning",
                "No GitHub Attestation Found",
                # States what was asked and what came back, and stops there.
                # This branch is reached by every failed download — timeouts,
                # 403 rate limits, 5xx, an unparseable body, even a local
                # write error — so naming a subject-digest mismatch as the
                # cause told operators with a perfectly good attestation to go
                # rewrite a correct workflow. The digest is still here, because
                # comparing it against `gh attestation list` is what actually
                # distinguishes the cases; the conclusion is left to whoever
                # can see both sides.
                (
                    f"Could not retrieve an attestation from GitHub for this SBOM. sbomify asked "
                    f"{github_org}/{github_repo}{repo_provenance} for subject digest "
                    f"sha256:{digest}, the SHA-256 of this SBOM as sbomify stored it. GitHub's "
                    f"response: {bundle.get('error', 'unknown')}. If the attestation exists and "
                    f"the digest above does not match its subject, the workflow is attesting a "
                    f"different artifact, or attesting the SBOM before a later step rewrites it. "
                    f"If there is no attest step at all, add actions/attest-build-provenance for "
                    f"the file this SBOM is uploaded from."
                ),
                metadata={
                    "github_org": github_org,
                    "github_repo": github_repo,
                    "vcs_source": vcs_info.get("source", "unknown"),
                    # The digest is the whole diagnosis: an operator comparing it
                    # against `gh attestation list` sees immediately whether the
                    # subject is absent or merely different.
                    "subject_digest": f"sha256:{digest}",
                    "error": bundle.get("error", "unknown"),
                },
            )

        bundle_path = bundle.get("bundle_path")
        if not isinstance(bundle_path, str):
            return self._gha_finding(
                "warning",
                "GitHub Attestation Bundle Missing",
                "Bundle download reported success but returned no path.",
                metadata={"github_org": github_org, "github_repo": github_repo},
            )

        try:
            verified = self._verify_with_cosign(sbom_path, Path(bundle_path), identity_regexp)
        finally:
            if os.path.exists(bundle_path):
                try:
                    os.unlink(bundle_path)
                except OSError as exc:
                    logger.debug("Failed to clean up cosign bundle %s: %s", bundle_path, exc)

        if verified.get("verified"):
            return self._gha_finding(
                "pass",
                "GitHub Attestation Verified",
                f"Successfully verified SBOM attestation from {github_org}/{github_repo}.",
                metadata={
                    "github_org": github_org,
                    "github_repo": github_repo,
                    "vcs_source": vcs_info.get("source", "unknown"),
                    "certificate_identity": identity_regexp,
                    "oidc_issuer": self.certificate_oidc_issuer,
                },
            )
        return self._gha_finding(
            "warning",
            "GitHub Attestation Verification Failed",
            verified.get("message", "cosign verify-blob-attestation reported a failure."),
            metadata={
                "github_org": github_org,
                "github_repo": github_repo,
                "error": verified.get("message", "unknown"),
            },
        )

    @staticmethod
    def _gha_finding(
        status: str,
        title: str,
        description: str,
        metadata: dict[str, Any],
    ) -> Finding:
        return Finding(
            id="verification:github-attestation",
            title=title,
            description=description,
            status=status,
            severity="info" if status == "pass" else ("medium" if status == "warning" else "high"),
            metadata=metadata,
        )

    @staticmethod
    def _is_rate_limited(response: requests.Response) -> bool:
        """GitHub signals a rate limit as a 429, or as a 403 with no quota left.

        A 403 is also how GitHub refuses access outright, so the remaining-quota
        header or the message is what tells the two apart.
        """
        if response.status_code == 429:
            return True
        if response.status_code != 403:
            return False
        if response.headers.get("X-RateLimit-Remaining") == "0":
            return True
        return "rate limit" in response.text.lower()

    @staticmethod
    def _rate_limit_retry_after_seconds(response: requests.Response) -> int:
        """Honor GitHub's wait headers, with an hour fallback for an unknown reset."""
        delays = []
        if retry_after := response.headers.get("Retry-After"):
            try:
                seconds = int(retry_after)
                if seconds >= 0:
                    delays.append(max(1, seconds))
            except ValueError:
                pass
        if response.headers.get("X-RateLimit-Remaining") == "0":
            try:
                reset = int(response.headers.get("X-RateLimit-Reset", ""))
                # Retry after the reset second rather than racing its boundary.
                delays.append(max(1, math.ceil(reset - time.time()) + 1))
            except ValueError:
                delays.append(3600)
        return max(delays, default=3600)

    def _download_github_bundle(self, org: str, repo: str, digest: str, repo_provenance: str = "") -> dict[str, Any]:
        """Fetch the attestation bundle from GitHub's public Attestations API.

        Raises ``AttestationNotYetAvailableError`` on ``404`` and
        ``GitHubRateLimitedError`` on a rate limit so the task layer can
        schedule a retry.
        """
        api_url = f"https://api.github.com/repos/{org}/{repo}/attestations/sha256:{digest}"
        logger.info("Fetching attestation from %s", api_url)

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        # Unauthenticated calls share 60 requests an hour per egress IP across
        # every workspace; a token raises that to 5,000.
        if token := settings.GITHUB_API_TOKEN:
            headers["Authorization"] = f"Bearer {token}"

        try:
            session = get_http_session()
            response = session.get(api_url, headers=headers, timeout=self.timeout)
        except requests.Timeout:
            return {"success": False, "error": "Attestation bundle download timed out"}
        except requests.RequestException as exc:
            return {"success": False, "error": f"Error fetching attestation from GitHub: {exc}"}

        if response.status_code == 404:
            # If the retries run out, this message and title become the
            # finding the user reads, so it has to carry the one fact that
            # distinguishes "not published yet" from "will never match": what
            # the digest is a digest OF. A 404 here is indistinguishable
            # between the two, and attesting a different subject (the container
            # image, or a copy of the SBOM written before augmentation rewrote
            # it) is the failure mode that never resolves however long we retry.
            raise AttestationNotYetAvailableError(
                f"GitHub returned no attestation for this SBOM from {org}/{repo}{repo_provenance}. "
                f"sbomify asked for the SHA-256 of the SBOM as sbomify stored it: sha256:{digest}. "
                f"If the workflow has no attest step, add actions/attest-build-provenance for the "
                f"file you upload. If it already attests, it attested a different file, such as a "
                f"container image or the SBOM before a later step changed it. sbomify cannot see "
                f"private repositories, so a private repository also returns nothing.",
                title="No attestation found",
            )
        if self._is_rate_limited(response):
            raise GitHubRateLimitedError(
                f"GitHub refused the attestation lookup for this SBOM from {org}/{repo}{repo_provenance} "
                f"because sbomify reached GitHub's API rate limit. This says nothing about the SBOM or its "
                f"attestation. sbomify asked for sha256:{digest}. Run the assessment again later.",
                title="GitHub rate limit reached",
                retry_after_seconds=self._rate_limit_retry_after_seconds(response),
            )
        if response.status_code != 200:
            return {
                "success": False,
                "error": f"GitHub API error: {response.status_code} - {response.text}",
            }

        # GitHub's edge can return HTML on rate-limit / abuse / 5xx pages
        # even when the upstream status code arrived as 200 (rare but
        # observed). Guard the JSON parse so the run records an
        # auditable error rather than crashing the worker.
        try:
            data = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            return {
                "success": False,
                "error": f"GitHub API returned an invalid JSON response: {exc}",
            }
        attestations = data.get("attestations", [])
        if not attestations:
            return {"success": False, "error": "No attestations returned from GitHub API"}

        bundle = attestations[0].get("bundle")
        if not bundle:
            return {"success": False, "error": "Attestation response missing bundle data"}

        # mkstemp creates files with 0o600 by default, avoiding the
        # post-creation chmod race that ``NamedTemporaryFile`` permits.
        try:
            fd, temp_path = tempfile.mkstemp(suffix=".json")
            with os.fdopen(fd, "w") as handle:
                json.dump(bundle, handle)
            return {"success": True, "bundle_path": temp_path}
        except OSError as exc:
            return {"success": False, "error": f"Failed to write bundle file: {exc}"}

    def _verify_with_cosign(
        self,
        sbom_path: Path,
        bundle_path: Path,
        identity_regexp: str,
    ) -> dict[str, Any]:
        cosign_path = shutil.which("cosign")
        if not cosign_path:
            return {
                "verified": False,
                "message": "cosign binary not found — install cosign to verify GitHub attestations.",
            }

        cmd = [
            cosign_path,
            "verify-blob-attestation",
            "--bundle",
            str(bundle_path),
            "--new-bundle-format",
            "--type",
            self.GITHUB_ATTESTATION_PREDICATE_TYPE,
            "--certificate-identity-regexp",
            identity_regexp,
            "--certificate-oidc-issuer",
            self.certificate_oidc_issuer,
            str(sbom_path),
        ]
        logger.debug("Running cosign: %s", " ".join(cmd))

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return {"verified": False, "message": "cosign verify-blob-attestation timed out"}
        except OSError as exc:
            return {"verified": False, "message": f"Failed to launch cosign: {exc}"}

        if result.returncode == 0:
            return {"verified": True, "message": "ok"}
        error_msg = result.stderr.strip() or result.stdout.strip() or "unknown error"
        return {"verified": False, "message": f"cosign returned {result.returncode}: {error_msg}"}

    # ------------------------------------------------------------------
    # VCS extraction (ported from the github-attestation plugin)
    # ------------------------------------------------------------------

    def _extract_vcs_info(self, sbom_data: dict[str, Any]) -> dict[str, str] | None:
        """Resolve the GitHub repository this SBOM points at, and where from.

        The ``source`` key is what stops a caller putting a dependency's
        repository in front of a user unqualified. ``document`` means the
        SBOM's own subject declared it; anything else means it was inferred
        from a package or component entry, which for a Python SBOM is
        typically an upstream project nobody here controls. Defaulted here
        rather than at each return so a format handler that forgets to tag its
        result is treated as the cautious case rather than as the document's
        own.
        """
        if is_spdx3(sbom_data):
            resolved = self._extract_vcs_info_spdx3(sbom_data)
        elif "spdxVersion" in sbom_data or "SPDXID" in sbom_data:
            resolved = self._extract_vcs_info_spdx(sbom_data)
        else:
            resolved = self._extract_vcs_info_cyclonedx(sbom_data)

        if resolved is not None and "source" not in resolved:
            resolved = {**resolved, "source": "package"}
        return resolved

    def _extract_vcs_info_cyclonedx(self, sbom_data: dict[str, Any]) -> dict[str, str] | None:
        for path in (
            sbom_data.get("metadata", {}).get("component", {}).get("externalReferences", []),
            sbom_data.get("externalReferences", []),
        ):
            url = self._find_vcs_url_cyclonedx(path)
            if url:
                parsed = self._parse_github_url(url)
                if parsed:
                    return {**parsed, "source": "document"}

        # Falling back to a dependency's repository. Recorded, because the
        # difference matters to anything that puts the name in front of a
        # reader: this is somebody else's project, and advice to go and change
        # that workflow is advice about a repository they do not own.
        for comp in sbom_data.get("components", []):
            url = self._find_vcs_url_cyclonedx(comp.get("externalReferences", []))
            if url:
                parsed = self._parse_github_url(url)
                if parsed:
                    return {**parsed, "source": "component"}
        return None

    def _extract_vcs_info_spdx3(self, sbom_data: dict[str, Any]) -> dict[str, str] | None:
        elements = sbom_data.get("@graph", sbom_data.get("elements", []))
        for element in elements:
            elem_type = element.get("type", element.get("@type", ""))
            if "software_Package" not in elem_type and elem_type != "Package":
                continue

            download_location = element.get("software_downloadLocation", "")
            if download_location and download_location not in ("NOASSERTION", "NONE"):
                vcs_url = self._parse_spdx_download_location(download_location) or download_location
                parsed = self._parse_github_url(vcs_url)
                if parsed:
                    return parsed

            for ref in element.get("externalRef", []):
                if str(ref.get("externalRefType", "")).lower() != "vcs":
                    continue
                locators = ref.get("locator") or []
                if isinstance(locators, str):
                    locators = [locators]
                for locator in locators:
                    parsed = self._parse_github_url(locator) if locator else None
                    if parsed:
                        return parsed
        return None

    def _extract_vcs_info_spdx(self, sbom_data: dict[str, Any]) -> dict[str, str] | None:
        # packages[0] is the document's subject by convention rather than by
        # guarantee, so every return below is tagged package-derived for the
        # same reason as the CycloneDX component fallback above.
        packages = sbom_data.get("packages", [])
        if not packages:
            return None

        main_pkg = packages[0]
        download_location = main_pkg.get("downloadLocation", "")
        if download_location and download_location not in ("NOASSERTION", "NONE"):
            vcs_url = self._parse_spdx_download_location(download_location)
            if vcs_url:
                parsed = self._parse_github_url(vcs_url)
                if parsed:
                    return parsed

        for ref in main_pkg.get("externalRefs", []):
            if str(ref.get("referenceType", "")).lower() == "vcs":
                locator = ref.get("referenceLocator", "")
                parsed = self._parse_github_url(locator) if locator else None
                if parsed:
                    return parsed
        return None

    @staticmethod
    def _parse_spdx_download_location(download_location: str) -> str | None:
        if not download_location.startswith("git+"):
            return None
        url_part = download_location[4:]
        if "@" in url_part:
            url_part = url_part.rsplit("@", 1)[0]
        return url_part

    def _find_vcs_url_cyclonedx(self, external_refs: list[dict[str, Any]]) -> str | None:
        for ref in external_refs:
            ref_type = str(ref.get("type", "")).lower()
            url = str(ref.get("url", ""))
            if ref_type in ("vcs", "git") and self._is_github_url(url):
                return url
        return None

    @staticmethod
    def _is_github_url(url: str) -> bool:
        if not url:
            return False
        if url.startswith("git@github.com:"):
            return True
        try:
            return urlparse(url).netloc == "github.com"
        except Exception:
            return False

    @staticmethod
    def _parse_github_url(url: str) -> dict[str, str] | None:
        # ``removesuffix`` (PEP 616) strips the literal ``.git`` extension.
        # The previously-used ``rstrip('.git')`` was a longstanding bug:
        # ``rstrip`` treats its argument as a *charset*, so "widget" → "widge".
        if url.startswith("git@github.com:"):
            path = url.removeprefix("git@github.com:").removesuffix(".git")
            parts = path.split("/")
            if len(parts) >= 2:
                return {"org": parts[0], "repo": parts[1].split("@")[0]}
            return None
        try:
            parsed = urlparse(url)
            if parsed.netloc != "github.com":
                return None
            path = parsed.path.strip("/").removesuffix(".git")
            parts = path.split("/")
            if len(parts) >= 2:
                return {"org": parts[0], "repo": parts[1].split("@")[0]}
        except Exception as exc:
            logger.debug("Failed to parse GitHub URL %r: %s", url, exc)
        return None

    # ------------------------------------------------------------------
    # 5. Aggregating attestation summary
    # ------------------------------------------------------------------

    @staticmethod
    def _attestation_summary(findings: list[Finding]) -> Finding:
        """Consolidate cryptographic findings into one pass/fail signal.

        BSI / FDA / etc. use the orchestrator's ``_is_passing`` aggregation
        on this plugin's run to satisfy ``requires_one_of: attestation``.
        Without this summary, a digest-pass plus all-warnings would still
        report ``pass_count > 0`` and falsely satisfy the requirement —
        despite no attestation source ever being verified. The summary
        emits ``fail`` when no cryptographic source verified, forcing
        ``fail_count > 0`` so the orchestrator does not consider the run
        passing.
        """
        crypto_findings = [
            f
            for f in findings
            if f.id in SBOMVerificationPlugin._CRYPTO_FINDING_IDS or f.id == "verification:github-attestation"
        ]
        passed = [f for f in crypto_findings if f.status == "pass"]
        failed = [f for f in crypto_findings if f.status == "fail"]

        if passed:
            sources = ", ".join(sorted({f.id.split(":", 1)[1] for f in passed}))
            return Finding(
                id="verification:attestation",
                title="Attestation Verified",
                description=f"At least one cryptographic source verified the SBOM: {sources}.",
                status="pass",
                severity="info",
                metadata={
                    "sources_passed": [f.id for f in passed],
                    "sources_failed": [f.id for f in failed],
                },
            )

        if failed:
            sources = ", ".join(sorted({f.id.split(":", 1)[1] for f in failed}))
            return Finding(
                id="verification:attestation",
                title="Attestation Verification Failed",
                description=(
                    f"Attestation source(s) ran but none verified the SBOM: {sources}. "
                    "Review the individual sub-findings for details."
                ),
                status="fail",
                severity="high",
                metadata={"sources_failed": [f.id for f in failed]},
            )

        return Finding(
            id="verification:attestation",
            title="No Attestation Source Available",
            description=(
                "No cryptographic attestation could be verified for this SBOM. "
                "Attach a cosign-bundle signature, a provenance attestation, or "
                "publish the SBOM via GitHub Actions with artifact attestations enabled."
            ),
            status="fail",
            severity="high",
            metadata={"sources_passed": [], "sources_failed": []},
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict[str, Any] | None = None,
        context: SBOMContext | None = None,
    ) -> AssessmentResult:
        sbom_data = sbom_path.read_bytes()

        try:
            sbom_dict = json.loads(sbom_data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            sbom_dict = None

        findings: list[Finding] = [
            self._check_digest_integrity(sbom_data, context),
            self._check_signature_present(context),
            self._check_signature_valid(sbom_data, context),
            self._check_provenance_present(context),
            self._check_provenance_digest(context),
        ]
        verified_elsewhere = any(f.id in self._CRYPTO_FINDING_IDS and f.status == "pass" for f in findings)
        try:
            github = self._check_github_attestation(sbom_data, sbom_path, sbom_dict, context)
        except RetryLaterError as exc:
            # Waiting on GitHub only makes sense while nothing else has
            # verified the SBOM. Once a stored signature or provenance has,
            # retrying holds that result back for hours and, when the
            # retries run out, replaces it with an error.
            if not verified_elsewhere:
                raise
            github = self._gha_finding(
                "warning",
                exc.title or "No GitHub Attestation Found",
                str(exc),
                metadata={"reason": "not_retried_other_source_verified"},
            )
        if verified_elsewhere and github.status == "warning":
            # GitHub is one way to verify an SBOM, not a requirement. With
            # another source verified, its absence is worth noting, not
            # reviewing.
            github = dataclasses.replace(github, status="info", severity="info")
        findings.append(github)
        findings.append(self._attestation_summary(findings))

        pass_count = sum(1 for f in findings if f.status == "pass")
        fail_count = sum(1 for f in findings if f.status == "fail")
        warning_count = sum(1 for f in findings if f.status == "warning")
        info_count = sum(1 for f in findings if f.status == "info")

        summary = AssessmentSummary(
            total_findings=len(findings),
            pass_count=pass_count,
            fail_count=fail_count,
            warning_count=warning_count,
            error_count=0,
            info_count=info_count,
        )

        return AssessmentResult(
            plugin_name="sbom-verification",
            plugin_version=self.VERSION,
            category=AssessmentCategory.ATTESTATION.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=findings,
            metadata={
                "sbom_id": sbom_id,
                "file_path": str(sbom_path),
            },
        )

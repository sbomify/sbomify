"""SBOM Verification plugin for signature, provenance, and attestation checking.

This plugin unifies the previously-separate ``github-attestation`` and
``sbom-verification`` plugins into a single attestation-category check that
runs every available verification source in one pass:

1. Re-computes SHA-256 and compares to the stored digest.
2. Checks whether a sbomify-stored cryptographic signature is attached
   (cosign-bundle via the ``signature_blob_key`` on the SBOM row).
3. Validates the stored signature using the ``sigstore`` library
   (``Verifier.production().verify_artifact``) when supported.
4. Checks whether a sbomify-stored provenance attestation is attached
   and verifies its subject digest matches the SBOM hash.
5. If the SBOM declares a GitHub VCS link, fetches the GitHub Sigstore
   attestation bundle from the public Attestations API and verifies it
   with ``cosign verify-blob-attestation``.
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
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

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

logger = logging.getLogger(__name__)


class AttestationNotYetAvailableError(RetryLaterError):
    """Raised when GitHub returns 404 because the attestation isn't published yet.

    GitHub's attestation pipeline is asynchronous — a ``404`` immediately
    after a workflow run does not mean the attestation will never exist.
    Inheriting from ``RetryLaterError`` signals the task layer to schedule
    a retry rather than mark the run failed.
    """


class SBOMVerificationPlugin(AssessmentPlugin):
    """Unified SBOM signature, provenance, and attestation verification plugin.

    Produces up to seven findings. The first six are evidence sub-checks;
    the seventh ``verification:attestation`` is the consolidated pass/fail
    that drives ``_is_passing`` for upstream consumers (BSI, FDA, etc.).
    """

    VERSION = "2.0.0"

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
        from sbomify.apps.core.object_store import S3Client

        s3 = S3Client("SBOMS")
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

        # Per-source failures below emit ``warning`` rather than ``fail`` so
        # they don't drive ``fail_count > 0`` on the run when another source
        # (stored signature/provenance) has already verified the SBOM. The
        # aggregating ``verification:attestation`` summary is the single
        # ``fail`` signal for "no source verified" — it's what BSI's
        # ``requires_one_of: attestation`` consumes.
        bundle = self._download_github_bundle(github_org, github_repo, digest)
        if not bundle.get("success"):
            return self._gha_finding(
                "warning",
                "No GitHub Attestation Found",
                (
                    f"Could not download attestation from GitHub for this SBOM. "
                    f"Ensure the SBOM was generated by a GitHub Actions workflow with "
                    f"artifact attestations enabled. Error: {bundle.get('error', 'unknown')}"
                ),
                metadata={
                    "github_org": github_org,
                    "github_repo": github_repo,
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

    def _download_github_bundle(self, org: str, repo: str, digest: str) -> dict[str, Any]:
        """Fetch the attestation bundle from GitHub's public Attestations API.

        Raises ``AttestationNotYetAvailableError`` on ``404`` so the task
        layer can schedule a retry.
        """
        api_url = f"https://api.github.com/repos/{org}/{repo}/attestations/sha256:{digest}"
        logger.info("Fetching attestation from %s", api_url)

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
        except requests.Timeout:
            return {"success": False, "error": "Attestation bundle download timed out"}
        except requests.RequestException as exc:
            return {"success": False, "error": f"Error fetching attestation from GitHub: {exc}"}

        if response.status_code == 404:
            raise AttestationNotYetAvailableError(f"No attestation found yet for this SBOM (digest: sha256:{digest})")
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
        if is_spdx3(sbom_data):
            return self._extract_vcs_info_spdx3(sbom_data)
        if "spdxVersion" in sbom_data or "SPDXID" in sbom_data:
            return self._extract_vcs_info_spdx(sbom_data)
        return self._extract_vcs_info_cyclonedx(sbom_data)

    def _extract_vcs_info_cyclonedx(self, sbom_data: dict[str, Any]) -> dict[str, str] | None:
        for path in (
            sbom_data.get("metadata", {}).get("component", {}).get("externalReferences", []),
            sbom_data.get("externalReferences", []),
        ):
            url = self._find_vcs_url_cyclonedx(path)
            if url:
                parsed = self._parse_github_url(url)
                if parsed:
                    return parsed

        for comp in sbom_data.get("components", []):
            url = self._find_vcs_url_cyclonedx(comp.get("externalReferences", []))
            if url:
                parsed = self._parse_github_url(url)
                if parsed:
                    return parsed
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
        crypto_ids = {
            "verification:signature-valid",
            "verification:provenance-digest",
            "verification:github-attestation",
        }
        crypto_findings = [f for f in findings if f.id in crypto_ids]
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
            self._check_github_attestation(sbom_data, sbom_path, sbom_dict, context),
        ]
        findings.append(self._attestation_summary(findings))

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
            category=AssessmentCategory.ATTESTATION.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=findings,
            metadata={
                "sbom_id": sbom_id,
                "file_path": str(sbom_path),
            },
        )

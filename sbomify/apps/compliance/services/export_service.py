"""CRA export service — build ZIP package with all compliance artifacts."""

from __future__ import annotations

import hashlib
import json
import logging
import zipfile
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from django.conf import settings as django_settings
from django.urls import reverse
from django.utils.text import slugify

from sbomify.apps.compliance import audit
from sbomify.apps.compliance.models import (
    CRAExportPackage,
    CRAGeneratedDocument,
)
from sbomify.apps.compliance.services import export_signing
from sbomify.apps.compliance.services._manufacturer_policy import (
    is_placeholder_manufacturer as _is_placeholder_manufacturer,
)
from sbomify.apps.compliance.services._reference_data import (
    read_harmonised_standards_bytes,
)
from sbomify.apps.compliance.services.oscal_service import serialize_assessment_results
from sbomify.apps.compliance.services.pdf_service import markdown_to_pdf
from sbomify.apps.core.models import Component
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.services.contacts import get_manufacturer

if TYPE_CHECKING:
    from sbomify.apps.compliance.models import CRAAssessment
    from sbomify.apps.core.models import User

logger = logging.getLogger(__name__)

# Map document kinds to their paths inside the ZIP
_DOC_PATH_MAP: dict[str, str] = {
    "vdp": "documents/vulnerability-disclosure-policy.md",
    "risk_assessment": "documents/risk-assessment.md",
    "user_instructions": "documents/user-instructions.md",
    "decommissioning_guide": "documents/secure-decommissioning.md",
    "security_txt": "security.txt",
    "early_warning": "article-14/early-warning-template.md",
    "full_notification": "article-14/vulnerability-notification-template.md",
    "final_report": "article-14/final-report-template.md",
    "declaration_of_conformity": "declaration-of-conformity.md",
}

# CRA Annex references for manifest
_DOC_CRA_REF: dict[str, str] = {
    "vdp": "Annex I, Part II, §5-6",
    "risk_assessment": "Annex VII, §3",
    "user_instructions": "Annex II",
    "decommissioning_guide": "Annex I, Part I, §13",
    "security_txt": "RFC 9116 / BSI TR-03183-3",
    "early_warning": "Article 14 (≤24h)",
    "full_notification": "Article 14 (≤72h)",
    "final_report": "Article 14 (≤14d/1mo)",
    "declaration_of_conformity": "Article 28, Annex V",
}

# SBOM format → file extension for ZIP packaging
_FORMAT_EXT_MAP: dict[str, str] = {"cyclonedx": "cdx.json", "spdx": "spdx.json"}

# Single source of truth for the bundle's manifest schema version.
# Bump here; the integrity README and the manifest body both read from
# this constant so they can't drift. 1.0 was the original CRA export
# scaffolding; 1.1 added manufacturer.is_placeholder and the integrity
# block; 1.2 added the PDF renderings; 1.3 added integrity.signature.
_MANIFEST_FORMAT_VERSION = "1.3"

# Human-readable PDF document titles per CRA document kind. Used as
# the ``<title>`` of the rendered PDF (the PDF reader's tab/header)
# and in the worker logs when a render fails so the operator can
# tell which document broke without grepping the manifest. Keyed by
# the ``DocumentKind`` enum (rather than raw string literals) so a
# rename of the choice value gets a hard mypy / typo error here
# instead of silently dropping the entry on a stale string match.
_DOC_PDF_TITLE: dict[CRAGeneratedDocument.DocumentKind, str] = {
    CRAGeneratedDocument.DocumentKind.VDP: "Vulnerability Disclosure Policy",
    CRAGeneratedDocument.DocumentKind.RISK_ASSESSMENT: "CRA Risk Assessment",
    CRAGeneratedDocument.DocumentKind.USER_INSTRUCTIONS: "User Instructions (Annex II)",
    CRAGeneratedDocument.DocumentKind.DECOMMISSIONING_GUIDE: "Secure Decommissioning Guide",
    CRAGeneratedDocument.DocumentKind.EARLY_WARNING: "CRA Article 14 — Early Warning",
    CRAGeneratedDocument.DocumentKind.FULL_NOTIFICATION: "CRA Article 14 — Vulnerability Notification",
    CRAGeneratedDocument.DocumentKind.FINAL_REPORT: "CRA Article 14 — Final Report",
    CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY: "EU Declaration of Conformity",
}


def _integrity_readme(manifest_sha256: str, retain_until: Any, signature: dict[str, str] | None = None) -> str:
    """Human-readable bundle verification guide and retention notice.

    The commands below are tested end-to-end against the real bundle
    layout — running them from the extracted package root (the folder
    named ``cra-package-<product-slug>/`` inside the ZIP) produces
    ``manifest.json: OK`` and ``<path>: OK`` for every file listed in
    the manifest's ``files`` array.
    """
    return (
        "# Bundle Integrity\n\n"
        f"Manifest `format_version` **{_MANIFEST_FORMAT_VERSION}** — changes vs 1.0 (shipped in\n"
        "the initial CRA export scaffolding):\n\n"
        "- `manufacturer.is_placeholder: bool` — flags when the team\n"
        "  profile still carries a stub name. Downstream consumers can\n"
        "  reject bundles where this is `true` to keep invalid DoCs\n"
        "  from being signed (Annex V item 2).\n"
        "- `integrity` block — self-describes the hash algorithm and\n"
        "  the companion files (`metadata/manifest.sha256`,\n"
        "  `metadata/INTEGRITY.md`). Old consumers that read\n"
        "  `format_version: 1.0` should ignore unknown keys.\n"
        "- 1.2 — every Markdown document is now rendered to a sibling\n"
        "  `.pdf` and listed in the manifest beside the `.md` source.\n"
        "  The `.md` remains the source of truth (auditors verify the\n"
        "  hash against the manifest); the `.pdf` is a convenience\n"
        "  rendering for paper-shaped regulatory filings. If the\n"
        "  rendering pipeline was unavailable when the bundle was\n"
        "  built, the `.pdf` entry is simply absent — its omission\n"
        "  is benign.\n"
        "- 1.3: `integrity.signature` names the key that signed the ZIP,\n"
        "  present only when sbomify signed it.\n\n"
        "This CRA export bundle ships with two integrity primitives:\n\n"
        "- `metadata/manifest.json` — per-file SHA-256 hashes for every "
        "artifact listed in its `files` array. `metadata/manifest.json`, "
        "`metadata/manifest.sha256`, and this `metadata/INTEGRITY.md` are "
        "NOT listed (they are the integrity primitives themselves — "
        "listing them would be circular).\n"
        "- `metadata/manifest.sha256` — SHA-256 of `metadata/manifest.json` "
        "itself, so the manifest cannot be tampered with without "
        "detection.\n\n"
        "## 1. Verifying the manifest\n\n"
        "Run from the extracted bundle root (the `cra-package-<slug>/` "
        "directory inside the ZIP):\n\n"
        "```sh\n"
        "sha256sum -c metadata/manifest.sha256\n"
        "```\n\n"
        "Expected output: `metadata/manifest.json: OK`.\n\n"
        f"Expected digest (from `metadata/manifest.sha256`): `{manifest_sha256}`\n\n"
        "## 2. Verifying every individual artifact\n\n"
        "Again from the extracted bundle root:\n\n"
        "```sh\n"
        'jq -r \'.files[] | "\\(.sha256)  \\(.path | sub("^cra-package-[^/]*/"; ""))"\' \\\n'
        "  metadata/manifest.json | sha256sum -c -\n"
        "```\n\n"
        "Each file in the manifest prints `<path>: OK`. A non-zero exit "
        "code or any `FAILED` entry means the bundle has been modified "
        "since export. The `jq` `sub` expression strips the "
        "`cra-package-<slug>/` prefix so `sha256sum` resolves paths "
        "against the current working directory (the bundle root).\n\n"
        "## 3. About signatures\n\n"
        f"{_signature_section(signature)}"
        "## 4. Retention obligation\n\n"
        "Article 13(15) of Regulation (EU) 2024/2847 requires this evidence "
        "to be kept for ten years from placing the product on the market, or "
        "for the declared support period, whichever is longer.\n\n"
        f"**Keep this bundle until at least {retain_until:%d %B %Y}.**\n\n"
        "sbomify holds its own copy under the same floor and will not delete "
        "it earlier. That is not a substitute for the recipient's obligation: "
        "once this bundle leaves sbomify, retaining the copy you were given "
        "is yours to do, and any object-store lifecycle rule it comes to rest "
        "under must not expire it before the date above.\n"
    )


def _signature_section(signature: dict[str, str] | None) -> str:
    """Section 3 of INTEGRITY.md: how to check sbomify's signature, or how to add your own."""
    if signature is None:
        return (
            "sbomify does not sign the bundle itself. Operators who need a "
            "stronger integrity / provenance guarantee for regulatory filings "
            "should sign the whole ZIP downstream with `cosign sign-blob` "
            "or `gpg --detach-sign` and distribute the detached signature "
            "alongside the bundle. The self-hash above bounds the manifest's "
            "integrity; a downstream signature bounds the whole package.\n\n"
        )
    return (
        "sbomify signs this bundle. The signature downloads beside the ZIP, "
        "under the ZIP's file name with `.sig` added. It is an ECDSA P-256 "
        "signature over the ZIP's SHA-256, base64 encoded, made with sbomify's "
        f"export key `{signature['key_id']}`.\n\n"
        f"Get the public key from {signature['public_key_url']} and save it as "
        "`sbomify.pub`.\n\n"
        "Check the key before you trust the signature. Whoever can replace "
        "this ZIP and its signature can also replace the key URL and key id "
        "written here, so they only tell you which key to fetch. Print the "
        "key's SHA-256 fingerprint:\n\n"
        "```sh\n"
        "openssl pkey -pubin -in sbomify.pub -outform DER | sha256sum\n"
        "```\n\n"
        "Compare all 64 characters with the fingerprint you got from your "
        "sbomify operator, not from this bundle. The key id above is its "
        "first 16 characters. If they differ, do not trust the signature.\n\n"
        "Then run either command against the ZIP as you received it, not the "
        "extracted folder:\n\n"
        "```sh\n"
        "cosign verify-blob --key sbomify.pub --signature <bundle>.zip.sig \\\n"
        "  --insecure-ignore-tlog=true <bundle>.zip\n"
        "base64 -d <bundle>.zip.sig > signature.der\n"
        "openssl dgst -sha256 -verify sbomify.pub -signature signature.der <bundle>.zip\n"
        "```\n\n"
        "Both print `Verified OK`. sbomify does not record the signature in a "
        "public transparency log, because that would publish when each bundle "
        "was exported; `--insecure-ignore-tlog=true` tells cosign not to look "
        "for one.\n\n"
    )


def _article_14_reporting_readme() -> str:
    """Article 14 deadlines + ENISA Single Reporting Platform pointers.

    Uses a bullet list (not a pipe table) for the deadlines so it
    renders consistently in every markdown engine the bundle might be
    viewed in — GitHub, CommonMark-only static-site generators, and
    plain-text viewers like Apple Preview's markdown-to-PDF converter
    all render bullets identically; pipe tables are a GFM extension
    that several common viewers degrade to literal `|`-separated text
    runs with blank gaps between rows.
    """
    return (
        "# CRA Article 14 — Reporting Obligations\n\n"
        "Article 14 of Regulation (EU) 2024/2847 requires manufacturers to "
        "notify the competent CSIRT and ENISA when they become aware of an "
        "actively exploited vulnerability or a severe incident. **The "
        "reporting obligations apply from 2026-09-11**; until then, "
        "submissions are voluntary.\n\n"
        "## Deadlines\n\n"
        "- **≤24 hours — Early warning.** What happened, which Member "
        "States are affected, and whether the incident is suspected to "
        "be malicious. Template: `early-warning-template.md`.\n"
        "- **≤72 hours — Vulnerability / incident notification.** "
        "Vulnerability or incident notification with the corrective "
        "measures taken so far. Template: "
        "`vulnerability-notification-template.md`.\n"
        "- **≤14 days — Final vulnerability report.** Final report once "
        "the corrective measure has been applied. Template: "
        "`final-report-template.md`.\n"
        "- **≤1 month — Final incident report.** Final report for severe "
        "incidents. Template: `final-report-template.md`.\n\n"
        "## Submission channel\n\n"
        "Article 16 designates ENISA to operate the Single Reporting Platform "
        "(SRP). The SRP consumes the notifications above and routes them to "
        "the competent CSIRTs automatically. Submission interface:\n\n"
        "- EC portal: https://digital-strategy.ec.europa.eu/en/policies/cra-reporting\n"
        "- ENISA portal: https://portal.cra-srp.enisa.europa.eu/\n\n"
        "The SRP accepts notifications through its web portal only, so sbomify "
        "does not submit on the operator's behalf. In sbomify, CRA reports "
        "(Compliance, Reports) lay each notification out field by field as the "
        "portal asks for it, track the deadlines above and record each filing "
        "with its ENISA reference.\n"
    )


def _get_generated_doc_content(doc: CRAGeneratedDocument, storage_client: StorageClient | None = None) -> bytes | None:
    """Fetch document content from object storage."""
    try:
        if storage_client is None:
            storage_client = StorageClient("DOCUMENTS")
        return storage_client.get_file_data(django_settings.AWS_DOCUMENTS_STORAGE_BUCKET_NAME, doc.storage_key)
    except Exception:
        logger.exception("Failed to fetch document %s from storage", doc.storage_key)
        return None


def _get_sbom_content(sbom: SBOM, storage_client: StorageClient | None = None) -> bytes | None:
    """Fetch SBOM content from object storage."""
    if not sbom.sbom_filename:
        return None
    try:
        if storage_client is None:
            storage_client = StorageClient("SBOMS")
        return storage_client.get_sbom_data(sbom.sbom_filename)
    except Exception:
        logger.exception("Failed to fetch SBOM %s from storage", sbom.sbom_filename)
        return None


def build_export_package(
    assessment: CRAAssessment,
    user: User,
) -> ServiceResult[CRAExportPackage]:
    """Build a ZIP package containing all CRA compliance artifacts.

    ZIP structure:
        cra-package-{product-slug}/
        ├── declaration-of-conformity.md
        ├── oscal/
        │   ├── catalog.json
        │   └── assessment-results.json
        ├── sboms/
        │   └── {component-slug}.{ext}
        ├── documents/
        │   ├── vulnerability-disclosure-policy.md
        │   ├── risk-assessment.md
        │   ├── user-instructions.md
        │   └── secure-decommissioning.md
        ├── security.txt
        ├── article-14/
        │   ├── early-warning-template.md
        │   ├── vulnerability-notification-template.md
        │   └── final-report-template.md
        └── metadata/
            └── manifest.json
    """
    product = assessment.product
    # Mirror the presigned-URL filename convention: fall back to the
    # product id when slugify(name) returns empty (e.g. a name made
    # entirely of punctuation). Without this fallback, the bundle root
    # would be ``cra-package-/`` and every INTEGRITY.md command that
    # references ``cra-package-<slug>/`` would leave the slug segment
    # blank and confuse auditors.
    prefix = f"cra-package-{slugify(product.name) or product.id}"
    import tempfile

    manifest_files: list[dict[str, str]] = []
    # Resolved once, before the bundle is written, so the date embedded in
    # INTEGRITY.md and the one stored on the row are the same date — computing
    # it twice would let a build that straddles midnight disagree with itself.
    retain_until = CRAExportPackage.retention_floor(assessment)
    # Decided before the ZIP is written, so INTEGRITY.md and the manifest
    # describe the signature the bundle actually gets.
    signer = export_signing.signing_key()
    signature: dict[str, str] | None = None
    if signer is not None:
        kid = signer[1]
        signature = {
            "algorithm": export_signing.ALGORITHM,
            "encoding": export_signing.ENCODING,
            "key_id": kid,
            "public_key_url": django_settings.APP_BASE_URL.rstrip("/") + reverse("cra_export_key", kwargs={"kid": kid}),
        }
    # Spool to disk if ZIP exceeds 10MB to avoid OOM on large products
    buf = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024)

    # Create storage clients once for reuse across all fetches
    docs_storage = StorageClient("DOCUMENTS")
    sboms_storage = StorageClient("SBOMS")

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. OSCAL catalog
        catalog_json = json.dumps(assessment.oscal_assessment_result.catalog.catalog_json, indent=2)
        catalog_bytes = catalog_json.encode("utf-8")
        _write_to_zip(zf, f"{prefix}/oscal/catalog.json", catalog_bytes, manifest_files, "OSCAL Catalog")

        # 2. OSCAL assessment results
        ar_json = serialize_assessment_results(assessment.oscal_assessment_result)
        ar_bytes = ar_json.encode("utf-8")
        _write_to_zip(zf, f"{prefix}/oscal/assessment-results.json", ar_bytes, manifest_files, "OSCAL AR")

        # 3. Generated documents — every ``.md`` gets a sibling ``.pdf``
        # rendered via ``_write_md_with_pdf``; ``security.txt`` is plain
        # text per RFC 9116 so we stay on ``_write_to_zip`` for it.
        docs = CRAGeneratedDocument.objects.filter(assessment=assessment)
        for doc in docs:
            zip_path = _DOC_PATH_MAP.get(doc.document_kind)
            if not zip_path:
                continue
            content = _get_generated_doc_content(doc, storage_client=docs_storage)
            if content:
                cra_ref = _DOC_CRA_REF.get(doc.document_kind, "")
                full_path = f"{prefix}/{zip_path}"
                if zip_path.endswith(".md"):
                    # ``document_kind`` is a ``CharField(choices=...)`` so the
                    # raw value is a plain ``str``; convert to the enum so
                    # ``_DOC_PDF_TITLE`` (keyed by enum) resolves cleanly.
                    # ``DocumentKind(doc.document_kind)`` is safe here
                    # because ``_DOC_PATH_MAP`` already filtered out any
                    # unrecognised kind via the earlier ``continue``.
                    enum_kind = CRAGeneratedDocument.DocumentKind(doc.document_kind)
                    pdf_title = _DOC_PDF_TITLE.get(enum_kind, doc.document_kind)
                    _write_md_with_pdf(zf, full_path, content, manifest_files, cra_ref, pdf_title=pdf_title)
                else:
                    _write_to_zip(zf, full_path, content, manifest_files, cra_ref)

        # 4. SBOMs from product components — fetch only the latest SBOM per component
        from django.db.models import OuterRef, Subquery

        latest_sbom_subquery = SBOM.objects.filter(component=OuterRef("pk")).order_by("-created_at").values("pk")[:1]
        components = list(
            Component.objects.filter(products=product)
            .distinct()
            .annotate(latest_sbom_id=Subquery(latest_sbom_subquery))
        )
        sbom_ids = [c.latest_sbom_id for c in components if c.latest_sbom_id]
        sboms_by_id = {s.pk: s for s in SBOM.objects.filter(pk__in=sbom_ids)} if sbom_ids else {}

        for component in components:
            latest_sbom = sboms_by_id.get(component.latest_sbom_id) if component.latest_sbom_id else None
            if not latest_sbom:
                continue
            sbom_content = _get_sbom_content(latest_sbom, storage_client=sboms_storage)
            if sbom_content:
                ext = _FORMAT_EXT_MAP.get(latest_sbom.format, "json")
                sbom_path = f"{prefix}/sboms/{slugify(component.name)}-{component.id}.{ext}"
                _write_to_zip(zf, sbom_path, sbom_content, manifest_files, "Annex VII, §2")

        # 5. Harmonised-standards reference copy — so the bundle is
        # self-contained and auditors / notified bodies don't have to
        # chase the source JSON inside the sbomify codebase. The helper
        # returns ``None`` (already logged) on missing / unreadable
        # file; we simply skip the embedded copy in that case — the
        # rest of the export continues.
        standards_bytes = read_harmonised_standards_bytes()
        if standards_bytes is not None:
            _write_to_zip(
                zf,
                f"{prefix}/metadata/harmonised-standards.json",
                standards_bytes,
                manifest_files,
                "CRA standards reference",
            )

        # 6. Article 14 reporting README — documents the 2026-09-11
        # reporting deadline, the ENISA Single Reporting Platform, and
        # which template to use for each deadline. Rendered to PDF
        # alongside the ``.md`` so notified bodies that only accept
        # filings on paper still get a usable copy.
        _write_md_with_pdf(
            zf,
            f"{prefix}/article-14/README_REPORTING.md",
            _article_14_reporting_readme().encode("utf-8"),
            manifest_files,
            "Article 14 / Article 16",
            pdf_title="CRA Article 14 — Reporting Obligations",
        )

        # 7. Manifest — built after all other files are written so manifest_files
        # is complete. The manifest itself is NOT included in its own files list.
        manufacturer = get_manufacturer(assessment.team)
        manufacturer_name = manufacturer.name if manufacturer else ""
        manufacturer_name_is_placeholder = _is_placeholder_manufacturer(manufacturer_name)

        manifest = {
            "format_version": _MANIFEST_FORMAT_VERSION,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "product": {
                "id": product.id,
                "name": product.name,
            },
            "manufacturer": {
                "name": manufacturer_name,
                "address": manufacturer.address if manufacturer else "",
                "is_placeholder": manufacturer_name_is_placeholder,
            },
            "assessment_id": assessment.id,
            "cra_regulation": "EU 2024/2847",
            "product_category": assessment.product_category,
            "conformity_procedure": assessment.conformity_assessment_procedure,
            "integrity": {
                "hash_algorithm": "sha256",
                "manifest_hash_file": "metadata/manifest.sha256",
                "verification_doc": "metadata/INTEGRITY.md",
                **({"signature": signature} if signature else {}),
            },
            "files": manifest_files,
        }
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        manifest_path = f"{prefix}/metadata/manifest.json"
        zf.writestr(manifest_path, manifest_bytes)

        # 8. Self-hash of the manifest so a consumer can verify the
        # manifest hasn't been altered before trusting its per-file
        # hashes. The self-hash bounds the manifest's integrity; the
        # whole package is bounded by sbomify's detached signature when
        # an export key is configured, or by the operator's own
        # downstream signature as ``metadata/INTEGRITY.md`` describes.
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        # The checksum file declares the manifest path as
        # ``metadata/manifest.json`` (relative to the bundle root, not
        # the checksum file's own directory) because ``sha256sum -c``
        # resolves each entry against the working directory. INTEGRITY.md
        # tells operators to run the verification from the bundle root,
        # so the path here must match that working directory.
        zf.writestr(
            f"{prefix}/metadata/manifest.sha256",
            f"{manifest_sha256}  metadata/manifest.json\n".encode("utf-8"),
        )

        # 9. INTEGRITY.md — human-readable verification guide.
        zf.writestr(
            f"{prefix}/metadata/INTEGRITY.md",
            _integrity_readme(manifest_sha256, retain_until, signature).encode("utf-8"),
        )

    # Read entire ZIP into memory for hashing and upload. This is acceptable because
    # CRA export packages are typically <1MB (documents + SBOMs). The SpooledTemporaryFile
    # already spills to disk above 10MB, and we need the full bytes for SHA-256 hashing
    # and the subsequent storage upload anyway — streaming would require two passes.
    buf.seek(0)
    zip_bytes = buf.read()
    buf.close()
    content_hash = hashlib.sha256(zip_bytes).hexdigest()
    storage_key = f"compliance/exports/{assessment.id}/{content_hash}.zip"

    # The signature goes up first: a bundle whose INTEGRITY.md promises one
    # must not reach storage without it.
    if signer is not None:
        try:
            docs_storage.upload_data_as_file(
                django_settings.AWS_DOCUMENTS_STORAGE_BUCKET_NAME,
                f"{storage_key}.sig",
                export_signing.sign(zip_bytes, signer[0]),
            )
        except Exception:
            logger.exception("Failed to upload export signature to storage")
            return ServiceResult.failure("Failed to upload export signature to storage", status_code=502)

    # Upload to object storage (reuse the docs_storage client)
    try:
        docs_storage.upload_data_as_file(django_settings.AWS_DOCUMENTS_STORAGE_BUCKET_NAME, storage_key, zip_bytes)
    except Exception:
        logger.exception("Failed to upload export package to storage")
        return ServiceResult.failure("Failed to upload export package to storage", status_code=502)

    package = CRAExportPackage.objects.create(
        assessment=assessment,
        storage_key=storage_key,
        content_hash=content_hash,
        manifest=manifest,
        created_by=user,
        # Pinned at creation: the Art. 13(15) floor must survive later
        # changes to the product's declared support period.
        retain_until=retain_until,
        signing_key_id=signature["key_id"] if signature else "",
    )
    audit.log_export_created(
        user=user,
        assessment_id=assessment.id,
        team_id=assessment.team_id,
        package_id=package.id,
        content_hash=content_hash,
        signing_key_id=package.signing_key_id,
    )

    return ServiceResult.success(package)


def _write_to_zip(
    zf: zipfile.ZipFile,
    path: str,
    data: bytes,
    manifest_files: list[dict[str, str]],
    cra_reference: str,
) -> None:
    """Write data to ZIP and record in manifest."""
    zf.writestr(path, data)
    manifest_files.append(
        {
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "cra_reference": cra_reference,
        }
    )


def _write_md_with_pdf(
    zf: zipfile.ZipFile,
    md_path: str,
    md_bytes: bytes,
    manifest_files: list[dict[str, str]],
    cra_reference: str,
    *,
    pdf_title: str,
) -> None:
    """Write a markdown file and best-effort sibling PDF.

    Both copies share the same ``cra_reference`` so manifest readers
    can group them. The PDF is a convenience rendering — if WeasyPrint
    is unavailable or rendering fails (logged inside
    ``markdown_to_pdf``) we silently skip it and the bundle still
    ships the markdown source. Auditors verifying compliance against
    the manifest hashes only need the ``.md`` to be intact; the
    matching ``.pdf`` saves them from running pandoc themselves.
    """
    _write_to_zip(zf, md_path, md_bytes, manifest_files, cra_reference)
    if not md_path.endswith(".md"):
        return
    pdf_bytes = markdown_to_pdf(md_bytes.decode("utf-8", errors="replace"), title=pdf_title)
    if pdf_bytes is None:
        return
    pdf_path = md_path[: -len(".md")] + ".pdf"
    _write_to_zip(zf, pdf_path, pdf_bytes, manifest_files, cra_reference)


# CRA export bundle URLs expire in 15 minutes rather than the boto3
# default of 1 h. These URLs point at regulated evidence (Annex VII
# technical documentation); keeping the unauthenticated window tight
# reduces the blast radius of a leaked URL in a referer header,
# copy-pasted ticket, or mis-routed chat message. 900 s is still
# long enough for a human to click "Download" on the wizard.
_PRESIGNED_URL_EXPIRY_SECONDS = 900


def _presigned_url(package: CRAExportPackage, storage_key: str, suffix: str, content_type: str) -> str:
    """A short-lived URL that downloads ``storage_key`` as ``cra-package-<slug>-<hash12><suffix>``."""
    product_slug = slugify(package.assessment.product.name) or package.assessment.product.id
    filename = f"cra-package-{product_slug}-{package.content_hash[:12]}{suffix}"
    return StorageClient("DOCUMENTS").generate_presigned_url(
        django_settings.AWS_DOCUMENTS_STORAGE_BUCKET_NAME,
        storage_key,
        expires_in=_PRESIGNED_URL_EXPIRY_SECONDS,
        response_headers={
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
            "ResponseContentType": content_type,
        },
    )


def get_download_url(package: CRAExportPackage) -> ServiceResult[str]:
    """Generate a presigned URL for the CRA bundle ZIP.

    Returns a short-lived URL (see ``_PRESIGNED_URL_EXPIRY_SECONDS``)
    with a forced ``Content-Disposition: attachment`` header so the
    browser downloads the bundle instead of rendering the ZIP inline
    (which some viewers attempt for JSON-looking responses). The
    filename is set to a deterministic slug derived from the product
    name + short hash so auditors can tell bundles apart on disk.
    """
    try:
        return ServiceResult.success(_presigned_url(package, package.storage_key, ".zip", "application/zip"))
    except Exception:
        logger.exception("Failed to generate presigned URL")
        return ServiceResult.failure("Failed to generate download URL", status_code=500)


def get_signature_url(package: CRAExportPackage) -> ServiceResult[str | None]:
    """A presigned URL for the bundle's detached signature, or None when it is unsigned."""
    if not package.signing_key_id:
        return ServiceResult.success(None)
    try:
        return ServiceResult.success(_presigned_url(package, f"{package.storage_key}.sig", ".zip.sig", "text/plain"))
    except Exception:
        logger.exception("Failed to generate presigned signature URL")
        return ServiceResult.failure("Failed to generate signature download URL", status_code=500)

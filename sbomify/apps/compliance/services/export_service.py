"""CRA export service — build ZIP package with all compliance artifacts."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from django.conf import settings as django_settings
from django.utils.text import slugify

from sbomify.apps.compliance.models import (
    CRAExportPackage,
    CRAGeneratedDocument,
)
from sbomify.apps.compliance.services.oscal_service import serialize_assessment_results
from sbomify.apps.core.models import Component
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import ContactEntity

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


def _get_generated_doc_content(doc: CRAGeneratedDocument) -> bytes | None:
    """Fetch document content from S3."""
    try:
        from sbomify.apps.core.object_store import S3Client

        s3 = S3Client("DOCUMENTS")
        return s3.get_file_data(django_settings.AWS_DOCUMENTS_STORAGE_BUCKET_NAME, doc.storage_key)
    except Exception:
        logger.exception("Failed to fetch document %s from S3", doc.storage_key)
        return None


def _get_sbom_content(sbom: SBOM) -> bytes | None:
    """Fetch SBOM content from S3."""
    try:
        from sbomify.apps.core.object_store import S3Client

        s3 = S3Client("SBOMS")
        return s3.get_sbom_data(sbom.sbom_filename)
    except Exception:
        logger.exception("Failed to fetch SBOM %s from S3", sbom.sbom_filename)
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
    prefix = f"cra-package-{slugify(product.name)}"
    manifest_files: list[dict[str, str]] = []
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. OSCAL catalog
        catalog_json = json.dumps(assessment.oscal_assessment_result.catalog.catalog_json, indent=2)
        catalog_bytes = catalog_json.encode("utf-8")
        _write_to_zip(zf, f"{prefix}/oscal/catalog.json", catalog_bytes, manifest_files, "OSCAL Catalog")

        # 2. OSCAL assessment results
        ar_json = serialize_assessment_results(assessment.oscal_assessment_result)
        ar_bytes = ar_json.encode("utf-8")
        _write_to_zip(zf, f"{prefix}/oscal/assessment-results.json", ar_bytes, manifest_files, "OSCAL AR")

        # 3. Generated documents
        docs = CRAGeneratedDocument.objects.filter(assessment=assessment)
        for doc in docs:
            zip_path = _DOC_PATH_MAP.get(doc.document_kind)
            if not zip_path:
                continue
            content = _get_generated_doc_content(doc)
            if content:
                cra_ref = _DOC_CRA_REF.get(doc.document_kind, "")
                _write_to_zip(zf, f"{prefix}/{zip_path}", content, manifest_files, cra_ref)

        # 4. SBOMs from product components
        from django.db.models import Prefetch

        components = (
            Component.objects.filter(projects__products=product)
            .prefetch_related(Prefetch("sbom_set", queryset=SBOM.objects.order_by("-created_at")))
            .distinct()
        )
        for component in components:
            # sbom_set is prefetched and ordered by -created_at
            prefetched_sboms = list(component.sbom_set.all())
            latest_sbom = prefetched_sboms[0] if prefetched_sboms else None
            if not latest_sbom:
                continue
            sbom_content = _get_sbom_content(latest_sbom)
            if sbom_content:
                _FORMAT_EXT_MAP = {"cyclonedx": "cdx.json", "spdx": "spdx.json"}
                ext = _FORMAT_EXT_MAP.get(latest_sbom.format, "json")
                sbom_path = f"{prefix}/sboms/{slugify(component.name)}.{ext}"
                _write_to_zip(zf, sbom_path, sbom_content, manifest_files, "Annex VII, §2")

        # 5. Manifest — built after all other files are written so manifest_files
        #    is complete. The manifest itself is NOT included in its own files list.
        manufacturer = ContactEntity.objects.filter(profile__team=assessment.team, is_manufacturer=True).first()

        manifest = {
            "format_version": "1.0",
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "product": {
                "id": product.id,
                "name": product.name,
            },
            "manufacturer": {
                "name": manufacturer.name if manufacturer else "",
                "address": manufacturer.address if manufacturer else "",
            },
            "assessment_id": assessment.id,
            "cra_regulation": "EU 2024/2847",
            "product_category": assessment.product_category,
            "conformity_procedure": assessment.conformity_assessment_procedure,
            "files": manifest_files,
        }
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        manifest_path = f"{prefix}/metadata/manifest.json"
        zf.writestr(manifest_path, manifest_bytes)

    # Calculate hash of entire ZIP
    zip_bytes = buf.getvalue()
    content_hash = hashlib.sha256(zip_bytes).hexdigest()
    storage_key = f"compliance/exports/{assessment.id}/{content_hash}.zip"

    # Upload to S3
    try:
        from sbomify.apps.core.object_store import S3Client

        s3 = S3Client("DOCUMENTS")
        s3.upload_data_as_file(django_settings.AWS_DOCUMENTS_STORAGE_BUCKET_NAME, storage_key, zip_bytes)
    except Exception:
        logger.exception("Failed to upload export package to S3")
        return ServiceResult.failure("Failed to upload export package to storage", status_code=502)

    package = CRAExportPackage.objects.create(
        assessment=assessment,
        storage_key=storage_key,
        content_hash=content_hash,
        manifest=manifest,
        created_by=user,
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


def get_download_url(package: CRAExportPackage) -> ServiceResult[str]:
    """Generate a presigned S3 URL for ZIP download (1 hour expiry)."""
    try:
        import boto3

        s3_client = boto3.client(
            "s3",
            region_name=django_settings.AWS_REGION,
            endpoint_url=django_settings.AWS_ENDPOINT_URL_S3,
            aws_access_key_id=django_settings.AWS_DOCUMENTS_ACCESS_KEY_ID,
            aws_secret_access_key=django_settings.AWS_DOCUMENTS_SECRET_ACCESS_KEY,
        )
        url: str = s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": django_settings.AWS_DOCUMENTS_STORAGE_BUCKET_NAME,
                "Key": package.storage_key,
            },
            ExpiresIn=3600,
        )
        return ServiceResult.success(url)
    except Exception:
        logger.exception("Failed to generate presigned URL")
        return ServiceResult.failure("Failed to generate download URL", status_code=500)

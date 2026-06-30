"""
SBOM Builder Factory and Format-Specific Builders.

This module provides a factory pattern for creating SBOM builders that support
multiple output formats (CycloneDX, SPDX) and versions.

Usage:
    from sbomify.apps.sboms.builders import get_sbom_builder, SBOMFormat, SBOMVersion

    # Get a CycloneDX 1.6 builder for releases
    builder = get_sbom_builder(
        entity_type="release",
        output_format=SBOMFormat.CYCLONEDX,
        version=SBOMVersion.CDX_1_6,
        entity=release,
        user=request.user,
    )
    sbom = builder(target_folder)

    # Get an SPDX 2.3 builder for releases
    builder = get_sbom_builder(
        entity_type="release",
        output_format=SBOMFormat.SPDX,
        version=SBOMVersion.SPDX_2_3,
        entity=release,
        user=request.user,
    )
    sbom = builder(target_folder)
"""

from __future__ import annotations

import importlib.metadata
import json
import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Protocol
from uuid import uuid4

from django.conf import settings
from django.utils import timezone

from sbomify.apps.sboms.sbom_format_schemas import cyclonedx_1_6 as cdx16
from sbomify.apps.sboms.sbom_format_schemas import cyclonedx_1_7 as cdx17
from sbomify.apps.sboms.sbom_format_schemas import spdx_2_3 as spdx23

log = logging.getLogger(__name__)

# Upper bound on concurrent member-SBOM S3 fetches during a cold aggregate build.
# Each fetch opens its own S3 connection, so this caps the connection fan-out per
# download. Tune down on small boxes; tune up if release sizes and S3 latency make
# the fetch the dominant cost.
MAX_AGGREGATE_FETCH_WORKERS = 8


class SBOMFormat(str, Enum):
    """Supported SBOM output formats."""

    CYCLONEDX = "cyclonedx"
    SPDX = "spdx"


class SBOMVersion(str, Enum):
    """Supported SBOM format versions."""

    # CycloneDX versions
    CDX_1_6 = "1.6"
    CDX_1_7 = "1.7"

    # SPDX versions
    SPDX_2_3 = "2.3"
    SPDX_3_0 = "3.0"


class SBOMBuilderProtocol(Protocol):
    """Protocol defining the interface for SBOM builders."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Build the SBOM and return the result."""
        ...


class BaseSBOMBuilder(ABC):
    """
    Abstract base class for SBOM builders.

    Defines the common interface and shared functionality for building SBOMs
    in different formats (CycloneDX, SPDX) and versions.
    """

    def __init__(self, entity: Any = None, user: Any = None):
        """
        Initialize the builder.

        Args:
            entity: The entity (product or release) to build SBOM for
            user: User for signed URL generation
        """
        self.entity = entity
        self.user = user
        self.temp_files: list[Path] = []
        self.target_folder: Optional[Path] = None
        # Set when a member SBOM fetch fails (non-fatal — the member is skipped).
        # Callers use this to avoid caching an incomplete aggregate (#998).
        self.had_member_fetch_error: bool = False

    @property
    @abstractmethod
    def format(self) -> SBOMFormat:
        """Return the SBOM format this builder produces."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Return the format version this builder produces."""
        ...

    @abstractmethod
    def build(self) -> Any:
        """Build and return the SBOM object."""
        ...

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """
        Build the SBOM.

        Supports both (target_folder) and (entity, target_folder) patterns.
        """
        from sbomify.apps.sboms.utils import temporary_sbom_files

        # Support both (target_folder) and (entity, target_folder)
        if len(args) == 1 and self.entity is not None:
            target_folder = args[0]
        elif len(args) == 2:
            self.entity, target_folder = args
        else:
            raise TypeError(f"{self.__class__.__name__}.__call__() expects (target_folder) or (entity, target_folder)")

        self.target_folder = Path(target_folder)

        # Use context manager for automatic cleanup
        with temporary_sbom_files() as temp_files:
            self.temp_files = temp_files
            return self.build()

    def get_tool_info(self) -> dict[str, str]:
        """Get common tool information for metadata."""
        return {
            "vendor": "sbomify, ltd",
            "name": "sbomify",
            "version": importlib.metadata.version("sbomify"),
        }

    def download_sbom_file(self, sbom: Any) -> tuple[Path, str] | None:
        """
        Download a specific SBOM file with cleanup tracking.

        Args:
            sbom: The SBOM instance to download

        Returns:
            Tuple of (Path to downloaded file, SBOM ID) or None
        """
        from sbomify.apps.core.object_store import S3Client

        if not sbom.sbom_filename:
            return None

        try:
            s3_client = S3Client("SBOMS")
            sbom_data = s3_client.get_sbom_data(sbom.sbom_filename)
            download_path = self.target_folder / sbom.sbom_filename
            download_path.write_bytes(sbom_data)

            # Track file for cleanup
            self.temp_files.append(download_path)

            return download_path, str(sbom.id)
        except Exception as e:
            log.warning(f"Failed to download SBOM {sbom.sbom_filename}: {e}")
            # A transient fetch error skips this member; flag the build as
            # incomplete so the partial aggregate is not cached (#998).
            self.had_member_fetch_error = True
            return None

    def _prefetch_member_files(self, sbom_instances: list[Any]) -> dict[str, tuple[Path, str] | None]:
        """Download member SBOM files concurrently, returning {str(sbom.id): result}.

        Parallelizes only the S3 I/O; callers still iterate members serially to
        build the aggregate deterministically. ``download_sbom_file`` is safe to
        run across threads: it constructs a fresh ``S3Client`` per call, touches
        no ORM, and its only shared writes (``temp_files.append`` /
        ``had_member_fetch_error``) are GIL-atomic. Output files are named by
        ``sbom.sbom_filename``, which is the content sha256, so two members can
        only collide on a filename when their bytes are identical — a concurrent
        overwrite then writes the same bytes and the aggregate is unaffected.
        """
        if not sbom_instances:
            return {}
        workers = min(len(sbom_instances), MAX_AGGREGATE_FETCH_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = executor.map(self.download_sbom_file, sbom_instances)
        return {str(sbom.id): result for sbom, result in zip(sbom_instances, results)}

    def _members_with_files(self, release: Any) -> tuple[list[Any], dict[str, tuple[Path, str] | None]]:
        """Filtered release members paired with their concurrently-fetched files.

        Centralizes the access-control filter (a public release hides non-public
        members) and the parallel prefetch shared by every release builder, so the
        rules can't drift between the CycloneDX and SPDX builders. Returns
        ``(members, {str(sbom.id): (path, id) | None})``.
        """
        from sbomify.apps.core.models import Component

        sbom_artifacts = (
            release.artifacts.filter(sbom__isnull=False)
            # select_related joins the whole sbom -> component -> team FK chain in
            # one query; a prefetch_related on the same path would just add a
            # redundant query.
            .select_related("sbom__component", "sbom__component__team")
            # Stable order so a content-addressed aggregate serializes identically
            # across rebuilds (the cache key is the artifact-set fingerprint).
            .order_by("sbom_id")
        )
        members = [
            artifact
            for artifact in sbom_artifacts
            if not (release.product.is_public and artifact.sbom.component.visibility != Component.Visibility.PUBLIC)
        ]
        fetched = self._prefetch_member_files([artifact.sbom for artifact in members])
        return members, fetched

    def select_best_sbom(self, sboms: list[Any]) -> Any:
        """
        Select the best SBOM from a list based on format preference.

        Uses format-aware selection to prefer SBOMs in the same format as the
        output being generated. Falls back to other formats if the preferred
        format isn't available.

        Args:
            sboms: List of SBOM instances to choose from

        Returns:
            The best matching SBOM, or None if no suitable SBOM found
        """
        from sbomify.apps.sboms.utils import select_sbom_by_format

        # Determine preferred format based on output format
        preferred = "cyclonedx" if self.format == SBOMFormat.CYCLONEDX else "spdx"
        return select_sbom_by_format(sboms, preferred_format=preferred, fallback=True)


# =============================================================================
# CycloneDX Builders
# =============================================================================


class BaseCycloneDXBuilder(BaseSBOMBuilder):
    """Base class for CycloneDX format builders."""

    @property
    def format(self) -> SBOMFormat:
        return SBOMFormat.CYCLONEDX

    @property
    @abstractmethod
    def cdx_module(self) -> Any:
        """Return the CycloneDX schema module for this version."""
        ...

    @property
    @abstractmethod
    def spec_version(self) -> str:
        """Return the CycloneDX spec version string."""
        ...

    @property
    @abstractmethod
    def schema_url(self) -> str:
        """Return the JSON schema URL for this version."""
        ...


class CycloneDX16Mixin:
    """Mixin providing CycloneDX 1.6 specific configuration."""

    @property
    def cdx_module(self) -> Any:
        return cdx16

    @property
    def spec_version(self) -> str:
        return "1.6"

    @property
    def version(self) -> str:
        return "1.6"

    @property
    def schema_url(self) -> str:
        return "http://cyclonedx.org/schema/bom-1.6.schema.json"


class CycloneDX17Mixin:
    """Mixin providing CycloneDX 1.7 specific configuration."""

    @property
    def cdx_module(self) -> Any:
        return cdx17

    @property
    def spec_version(self) -> str:
        return "1.7"

    @property
    def version(self) -> str:
        return "1.7"

    @property
    def schema_url(self) -> str:
        return "http://cyclonedx.org/schema/bom-1.7.schema.json"


class ReleaseCycloneDXBuilder(BaseCycloneDXBuilder):
    """
    Base CycloneDX builder for releases.

    Subclasses should mix in a version mixin (CycloneDX16Mixin or CycloneDX17Mixin).
    """

    def build(self) -> Any:
        """Build the release SBOM in CycloneDX format."""
        from sbomify.apps.sboms.utils import (
            create_component_type_mapping,
            create_external_reference,
            create_product_external_references,
            create_version_object,
            extract_component_info,
        )

        cdx = self.cdx_module
        release = self.entity

        # Create base SBOM structure
        sbom = cdx.CyclonedxSoftwareBillOfMaterialsStandard(bomFormat="CycloneDX", specVersion=self.spec_version)
        sbom.field_schema = self.schema_url
        sbom.serialNumber = f"urn:uuid:{uuid4()}"
        sbom.version = 1

        # Create main component with external references
        main_component = cdx.Component(
            name=f"{release.product.name} - {release.name}", type=cdx.Type.application, scope=cdx.Scope.required
        )

        # Add external references from product
        external_refs = create_product_external_references(release.product, user=self.user)
        if external_refs:
            main_component.externalReferences = external_refs

        # Build metadata section
        sbom.metadata = cdx.Metadata(
            timestamp=timezone.now(),
            tools=[
                cdx.Tool(
                    vendor=self.get_tool_info()["vendor"],
                    name=self.get_tool_info()["name"],
                    version=self.get_tool_info()["version"],
                    externalReferences=[
                        cdx.ExternalReference(type=cdx.Type3.website, url="https://sbomify.com"),
                        cdx.ExternalReference(type=cdx.Type3.vcs, url="https://github.com/sbomify/sbomify"),
                    ],
                )
            ],
            component=main_component,
        )

        # Build components section from release artifacts
        sbom.components = []

        component_type_mapping = create_component_type_mapping()

        members, fetched = self._members_with_files(release)

        for artifact in members:
            sbom_instance = artifact.sbom

            sbom_result = fetched.get(str(sbom_instance.id))
            if sbom_result is None:
                log.warning(f"SBOM for artifact {artifact.id} not found")
                continue

            sbom_path, sbom_id = sbom_result

            try:
                sbom_data = json.loads(sbom_path.read_text())
            except (json.JSONDecodeError, Exception) as e:
                log.error(f"Failed to read SBOM file {sbom_path.name}: {e}")
                continue

            # Extract component metadata
            component_dict = sbom_data.get("metadata", {}).get("component")
            if component_dict:
                name, component_type, version = extract_component_info(component_dict)
            else:
                # metadata.component is optional in CycloneDX; fall back to stored component name
                name = sbom_instance.component.name
                component_type = "library"
                version = ""

            # Create CycloneDX component
            try:
                from sbomify.apps.core.models import LATEST_RELEASE_NAME

                display_name = f"{release.name}/{name}" if release.name != LATEST_RELEASE_NAME else name

                component = cdx.Component(
                    name=display_name,
                    type=component_type_mapping.get(component_type, cdx.Type.library),
                    scope=cdx.Scope.required,
                )

                version_obj = create_version_object(version)
                if version_obj:
                    component.version = version_obj

                # Add external reference to original SBOM
                ext_ref = create_external_reference(sbom_path.name, sbom_id, self.user)
                if ext_ref:
                    component.externalReferences = [ext_ref]

                sbom.components.append(component)

            except Exception as e:
                log.warning(f"Failed to create component from SBOM {sbom_path.name}: {e}")
                continue

        return sbom


class ReleaseCycloneDX16Builder(CycloneDX16Mixin, ReleaseCycloneDXBuilder):
    """CycloneDX 1.6 builder for releases."""

    pass


class ReleaseCycloneDX17Builder(CycloneDX17Mixin, ReleaseCycloneDXBuilder):
    """CycloneDX 1.7 builder for releases."""

    pass


# =============================================================================
# SPDX Builders
# =============================================================================


class BaseSPDXBuilder(BaseSBOMBuilder):
    """Base class for SPDX format builders."""

    @property
    def format(self) -> SBOMFormat:
        return SBOMFormat.SPDX

    @property
    @abstractmethod
    def spdx_version_string(self) -> str:
        """Return the SPDX version string (e.g., 'SPDX-2.3')."""
        ...


class SPDX23Mixin:
    """Mixin providing SPDX 2.3 specific configuration."""

    @property
    def spdx_module(self) -> Any:
        return spdx23

    @property
    def version(self) -> str:
        return "2.3"

    @property
    def spdx_version_string(self) -> str:
        return "SPDX-2.3"


class ReleaseSPDXBuilder(BaseSPDXBuilder):
    """
    Base SPDX builder for releases.

    Subclasses should mix in a version mixin (SPDX23Mixin).
    """

    def build(self) -> spdx23.SPDXDocument:
        """
        Build the release SBOM in SPDX format.

        Returns an SPDX Pydantic model that can be serialized to JSON.
        """
        from sbomify.apps.sboms.utils import create_product_spdx_external_references

        release = self.entity
        timestamp = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")

        # Generate unique document namespace
        doc_uuid = str(uuid4())
        doc_namespace = f"https://sbomify.com/spdx/{release.product.id}/{release.id}/{doc_uuid}"

        # Build base SPDX document structure
        sbom: dict[str, Any] = {
            "spdxVersion": self.spdx_version_string,
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": f"{release.product.name} - {release.name}",
            "documentNamespace": doc_namespace,
            "creationInfo": {
                "created": timestamp,
                "creators": [
                    f"Organization: {self.get_tool_info()['vendor']}",
                    f"Tool: {self.get_tool_info()['name']}-{self.get_tool_info()['version']}",
                ],
            },
            "packages": [],
            "relationships": [],
            # SPDX-native cross-document links to member SBOMs (#357). Populated
            # per member below; members that can't be linked natively fall back
            # to a local stub package + download-URL externalRef.
            "externalDocumentRefs": [],
        }

        # Add document describes relationship for the main package
        main_package_id = "SPDXRef-Package-Main"
        sbom["documentDescribes"] = [main_package_id]

        # Create main package representing the release
        main_package: dict[str, Any] = {
            "SPDXID": main_package_id,
            "name": f"{release.product.name} - {release.name}",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "primaryPackagePurpose": "APPLICATION",
            # NTIA/CISA compliance: supplier info
            "supplier": f"Organization: {self.get_tool_info()['vendor']}",
        }

        # Add external references from product
        external_refs = create_product_spdx_external_references(release.product, user=self.user)
        if external_refs:
            # Filter out None comments
            main_package["externalRefs"] = [{k: v for k, v in ref.items() if v is not None} for ref in external_refs]

        sbom["packages"].append(main_package)

        # Add DESCRIBES relationship
        sbom["relationships"].append(
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relatedSpdxElement": main_package_id,
                "relationshipType": "DESCRIBES",
            }
        )

        # Build component packages from release artifacts
        members, fetched = self._members_with_files(release)

        from sbomify.apps.sboms.utils import spdx2_inbound_member_dependencies, spdx2_member_link

        package_index = 0
        doc_ref_index = 0
        # Native-linked members, for the inbound-resolve post-pass (#357): each is
        # (aggregate ref, content digest, parsed member doc); hash_to_related maps a
        # member's content hash to its aggregate ref so a member's inbound refs can
        # resolve to OTHER release members by digest.
        native_members: list[tuple[str, str, dict[str, Any]]] = []
        hash_to_related: dict[str, str] = {}
        for artifact in members:
            sbom_instance = artifact.sbom

            sbom_result = fetched.get(str(sbom_instance.id))
            if sbom_result is None:
                log.warning(f"SBOM for artifact {artifact.id} not found")
                continue

            sbom_path, sbom_id = sbom_result

            try:
                sbom_data = json.loads(sbom_path.read_text())
            except (json.JSONDecodeError, Exception) as e:
                log.error(f"Failed to read SBOM file {sbom_path.name}: {e}")
                continue

            # SPDX-native cross-document link (#357): for an SPDX 2.x member with a
            # documentNamespace + content hash, link to its real document instead
            # of flattening it into a local stub. Mixed/CDX members fall through.
            link = spdx2_member_link(sbom_instance, sbom_data, f"DocumentRef-{doc_ref_index + 1}")
            if link is not None:
                doc_ref_index += 1
                external_document_ref, related = link
                sbom["externalDocumentRefs"].append(external_document_ref)
                sbom["relationships"].append(
                    {
                        "spdxElementId": main_package_id,
                        "relatedSpdxElement": related,
                        "relationshipType": "CONTAINS",
                    }
                )
                native_members.append((related, sbom_instance.sha256_hash, sbom_data))
                hash_to_related[sbom_instance.sha256_hash] = related
                continue

            # Handle both CycloneDX and SPDX source SBOMs
            component_info = self._extract_component_info_from_sbom(sbom_data, sbom_path.name)
            if component_info is None:
                continue

            name, version, supplier = component_info
            package_index += 1
            package_id = f"SPDXRef-Package-{package_index}"

            # Create SPDX package for component
            package = {
                "SPDXID": package_id,
                "name": name,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "primaryPackagePurpose": "LIBRARY",
            }

            # Add version if available
            if version:
                package["versionInfo"] = str(version)

            # Add supplier if available (NTIA compliance)
            if supplier:
                package["supplier"] = supplier

            # Add external reference to original SBOM. ``sbom_instance`` is the
            # select_related-loaded artifact.sbom (same row sbom_id points to),
            # so re-fetching it per artifact is redundant (#998).
            from sbomify.apps.sboms.utils import get_download_url_for_sbom

            try:
                download_url = get_download_url_for_sbom(sbom_instance, self.user, settings.APP_BASE_URL)
                package["externalRefs"] = [
                    {
                        "referenceCategory": "OTHER",
                        "referenceType": "sbom",
                        "referenceLocator": download_url,
                    }
                ]
            except Exception as e:
                log.warning(f"Failed to add external ref for SBOM {sbom_id}: {e}")

            sbom["packages"].append(package)

            # Add CONTAINS relationship from main package
            sbom["relationships"].append(
                {
                    "spdxElementId": main_package_id,
                    "relatedSpdxElement": package_id,
                    "relationshipType": "CONTAINS",
                }
            )

        # Inbound resolve (#357): preserve a DEPENDS_ON edge for each cross-document
        # reference a member declares toward ANOTHER release member, resolved by
        # SHA-256 digest only (no external fetch). Dedup against existing edges.
        existing_rels = {
            (r["spdxElementId"], r["relatedSpdxElement"], r["relationshipType"]) for r in sbom["relationships"]
        }
        for member_ref, member_digest, member_data in native_members:
            for edge in spdx2_inbound_member_dependencies(member_data, member_ref, member_digest, hash_to_related):
                key = (edge["spdxElementId"], edge["relatedSpdxElement"], edge["relationshipType"])
                if key not in existing_rels:
                    existing_rels.add(key)
                    sbom["relationships"].append(edge)

        # Convert dict to Pydantic model for consistent serialization
        return spdx23.SPDXDocument.model_validate(sbom)

    def _extract_component_info_from_sbom(
        self, sbom_data: dict[str, Any], filename: str
    ) -> tuple[str, str | None, str | None] | None:
        """
        Extract component info from CycloneDX, SPDX 2.x, or SPDX 3.0 source SBOM.

        Returns:
            Tuple of (name, version, supplier) or None if extraction fails
        """
        from sbomify.apps.sboms.utils import extract_component_info

        # Try CycloneDX format first
        if sbom_data.get("bomFormat") == "CycloneDX":
            component_dict = sbom_data.get("metadata", {}).get("component")
            if component_dict:
                name, _, version = extract_component_info(component_dict)
                supplier = None
                # Try to get supplier from metadata
                metadata = sbom_data.get("metadata", {})
                if metadata.get("supplier"):
                    supplier_info = metadata["supplier"]
                    if isinstance(supplier_info, dict):
                        supplier = f"Organization: {supplier_info.get('name', 'Unknown')}"
                return name, str(version) if version else None, supplier

        # Try SPDX 3.0 format (spec-compliant @graph or legacy elements)
        elif "@graph" in sbom_data or (
            sbom_data.get("spdxVersion", "").startswith("SPDX-3.") and "elements" in sbom_data
        ):
            elements = sbom_data.get("@graph", sbom_data.get("elements", []))
            packages = [e for e in elements if e.get("type") == "software_Package"]
            if packages:
                pkg = packages[0]
                relationships = [e for e in elements if e.get("type") == "Relationship"]
                for rel in relationships:
                    if rel.get("relationshipType") == "describes":
                        target_ids = rel.get("to", [])
                        if target_ids:
                            for p in packages:
                                if p.get("spdxId") == target_ids[0]:
                                    pkg = p
                                    break
                name = pkg.get("name", "Unknown")
                version = pkg.get("software_packageVersion")
                supplier = None
                return name, version, supplier

        # Try SPDX 2.x format
        elif sbom_data.get("spdxVersion", "").startswith("SPDX-"):
            packages = sbom_data.get("packages", [])
            if packages:
                # Use first package or the one referenced by documentDescribes
                pkg = packages[0]
                doc_describes = sbom_data.get("documentDescribes", [])
                if doc_describes:
                    for p in packages:
                        if p.get("SPDXID") == doc_describes[0]:
                            pkg = p
                            break

                name = pkg.get("name", "Unknown")
                version = pkg.get("versionInfo")
                supplier = pkg.get("supplier")
                return name, version, supplier

        log.warning(f"Could not extract component info from {filename}")
        return None


class ReleaseSPDX23Builder(SPDX23Mixin, ReleaseSPDXBuilder):
    """SPDX 2.3 builder for releases."""

    pass


# =============================================================================
# SPDX 3.0 Builders
# =============================================================================


class SPDX30Mixin:
    """Mixin providing SPDX 3.0 specific configuration."""

    @property
    def version(self) -> str:
        return "3.0"

    @property
    def spdx_spec_version(self) -> str:
        return "3.0.1"

    @property
    def spdx_version_string(self) -> str:
        return f"SPDX-{self.spdx_spec_version}"

    @property
    def spdx_context(self) -> str:
        return f"https://spdx.org/rdf/{self.spdx_spec_version}/spdx-context.jsonld"


class ReleaseSPDX3Builder(BaseSPDXBuilder):
    """Base SPDX 3.0 builder for releases.

    Produces spec-compliant SPDX 3.0 output with @context/@graph structure.
    """

    @property
    @abstractmethod
    def spdx_spec_version(self) -> str:
        """Return the SPDX spec version string (e.g., '3.0.1')."""
        ...

    @property
    @abstractmethod
    def spdx_context(self) -> str:
        """Return the SPDX 3.0 JSON-LD context URL."""
        ...

    def build(self) -> dict[str, Any]:
        """Build the release SBOM in SPDX 3.0 format.

        Returns a dict with @context/@graph structure per the SPDX 3.0.1 spec.
        The SpdxDocument is an element inside @graph.
        CreationInfo is a shared blank node referenced by all elements.
        """

        release = self.entity
        timestamp = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")

        # Generate unique document namespace
        doc_uuid = str(uuid4())
        doc_namespace = f"https://sbomify.com/spdx/{release.product.id}/{release.id}/{doc_uuid}"
        tool_info = self.get_tool_info()

        # spdxIds for agents/tools
        org_spdx_id = f"{doc_namespace}#SPDXRef-Organization-sbomify"
        tool_spdx_id = f"{doc_namespace}#SPDXRef-Tool-sbomify"
        main_pkg_spdx_id = f"{doc_namespace}#SPDXRef-Package-Main"

        # CreationInfo as blank node element in @graph
        creation_info_element = {
            "type": "CreationInfo",
            "@id": "_:creationInfo",
            "specVersion": self.spdx_spec_version,
            "created": timestamp,
            "createdBy": [org_spdx_id],
            "createdUsing": [tool_spdx_id],
        }

        # All elements reference CreationInfo via blank node ID
        creation_info_ref = "_:creationInfo"

        # Build @graph elements
        graph: list[dict[str, Any]] = [creation_info_element]

        # Organization element
        graph.append(
            {
                "type": "Organization",
                "spdxId": org_spdx_id,
                "creationInfo": creation_info_ref,
                "name": tool_info["vendor"],
            }
        )

        # Tool element
        graph.append(
            {
                "type": "Tool",
                "spdxId": tool_spdx_id,
                "creationInfo": creation_info_ref,
                "name": tool_info["name"],
                "description": f"{tool_info['name']} {tool_info['version']}",
            }
        )

        # Main package element
        main_pkg = {
            "type": "software_Package",
            "spdxId": main_pkg_spdx_id,
            "creationInfo": creation_info_ref,
            "name": f"{release.product.name} - {release.name}",
            "software_downloadLocation": "NOASSERTION",
            "suppliedBy": org_spdx_id,
        }
        graph.append(main_pkg)

        # Process release artifacts
        members, fetched = self._members_with_files(release)

        from sbomify.apps.sboms.utils import (
            get_download_url_for_sbom,
            spdx3_inbound_member_dependency_uris,
            spdx3_member_import,
        )

        package_index = 0
        all_element_spdx_ids = [org_spdx_id, tool_spdx_id, main_pkg_spdx_id]
        # SPDX-native cross-document links (#357): import-map entries + the member
        # root-element URIs they point at (referenced from the describes edge).
        import_map: list[dict[str, Any]] = []
        external_member_uris: list[str] = []
        # Native-linked members for the inbound-resolve post-pass (#357):
        # (root URI, content digest, parsed doc) + a digest -> root-URI map.
        native3_members: list[tuple[str, str, dict[str, Any]]] = []
        hash_to_uri: dict[str, str] = {}

        for artifact in members:
            sbom_instance = artifact.sbom

            sbom_result = fetched.get(str(sbom_instance.id))
            if sbom_result is None:
                log.warning(f"SBOM for artifact {artifact.id} not found")
                continue

            sbom_path, sbom_id = sbom_result

            try:
                sbom_data = json.loads(sbom_path.read_text())
            except (json.JSONDecodeError, Exception) as e:
                log.error(f"Failed to read SBOM file {sbom_path.name}: {e}")
                continue

            # ``sbom_instance`` is the select_related-loaded artifact.sbom, so
            # re-fetching it per artifact is redundant (#998).
            try:
                download_url: str | None = get_download_url_for_sbom(sbom_instance, self.user, settings.APP_BASE_URL)
            except Exception as e:
                log.warning(f"Failed to build download URL for SBOM {sbom_id}: {e}")
                download_url = None

            # SPDX-native import-map link (#357): for an SPDX 3.0 member with a
            # content hash, reference its real root element via an import-map
            # entry instead of flattening it into a local stub package.
            if download_url:
                link = spdx3_member_import(sbom_instance, sbom_data, download_url)
                if link is not None:
                    import_entry, root_uri = link
                    import_map.append(import_entry)
                    external_member_uris.append(root_uri)
                    native3_members.append((root_uri, sbom_instance.sha256_hash, sbom_data))
                    hash_to_uri[sbom_instance.sha256_hash] = root_uri
                    continue

            component_info = self._extract_component_info_from_sbom(sbom_data, sbom_path.name)
            if component_info is None:
                continue

            name, version, supplier = component_info
            package_index += 1
            pkg_spdx_id = f"{doc_namespace}#SPDXRef-Package-{package_index}"
            all_element_spdx_ids.append(pkg_spdx_id)

            pkg_element: dict[str, Any] = {
                "type": "software_Package",
                "spdxId": pkg_spdx_id,
                "creationInfo": creation_info_ref,
                "name": name,
                "software_downloadLocation": "NOASSERTION",
            }

            if version:
                pkg_element["software_packageVersion"] = str(version)

            if download_url:
                pkg_element["externalRef"] = [
                    {
                        "type": "ExternalRef",
                        "externalRefType": "other",
                        "locator": [download_url],
                    }
                ]

            graph.append(pkg_element)

        # Add describes relationship (local stub packages + native external URIs)
        component_pkg_ids = [
            sid for sid in all_element_spdx_ids if "#SPDXRef-Package-" in sid and sid != main_pkg_spdx_id
        ] + external_member_uris
        rel_spdx_id = f"{doc_namespace}#SPDXRef-Relationship-describes"
        if component_pkg_ids:
            graph.append(
                {
                    "type": "Relationship",
                    "spdxId": rel_spdx_id,
                    "creationInfo": creation_info_ref,
                    "relationshipType": "describes",
                    "from": main_pkg_spdx_id,
                    "to": component_pkg_ids,
                }
            )
            all_element_spdx_ids.append(rel_spdx_id)

        # Inbound resolve (#357): a dependsOn relationship for each cross-document
        # reference a member declares toward ANOTHER release member, resolved by
        # SHA-256 digest only (the locationHint URL is never fetched). Deduped.
        dep_index = 0
        seen_deps: set[tuple[str, str]] = set()
        for member_uri, member_digest, member_data in native3_members:
            for target_uri in spdx3_inbound_member_dependency_uris(member_data, member_digest, hash_to_uri):
                if target_uri == member_uri or (member_uri, target_uri) in seen_deps:
                    continue
                seen_deps.add((member_uri, target_uri))
                dep_index += 1
                dep_id = f"{doc_namespace}#SPDXRef-Relationship-dependsOn-{dep_index}"
                graph.append(
                    {
                        "type": "Relationship",
                        "spdxId": dep_id,
                        "creationInfo": creation_info_ref,
                        "relationshipType": "dependsOn",
                        "from": member_uri,
                        "to": [target_uri],
                    }
                )
                all_element_spdx_ids.append(dep_id)

        # SpdxDocument element inside @graph
        doc_element: dict[str, Any] = {
            "type": "SpdxDocument",
            "spdxId": doc_namespace,
            "creationInfo": creation_info_ref,
            "name": f"{release.product.name} - {release.name}",
            "dataLicense": "CC0-1.0",
            "profileConformance": ["core", "software"],
            "element": all_element_spdx_ids,
            "rootElement": [main_pkg_spdx_id],
        }
        # Import map: one ExternalMap per natively-linked member (#357).
        if import_map:
            doc_element["import"] = import_map
        graph.append(doc_element)

        # Build root document with JSON-LD structure
        sbom = {
            "@context": self.spdx_context,
            "@graph": graph,
        }

        return sbom

    def _extract_component_info_from_sbom(
        self, sbom_data: dict[str, Any], filename: str
    ) -> tuple[str, str | None, str | None] | None:
        """Extract component info from either CycloneDX, SPDX 2.x, or SPDX 3.0 source SBOM."""
        from sbomify.apps.sboms.utils import extract_component_info

        # CycloneDX format
        if sbom_data.get("bomFormat") == "CycloneDX":
            component_dict = sbom_data.get("metadata", {}).get("component")
            if component_dict:
                name, _, version = extract_component_info(component_dict)
                supplier = None
                metadata = sbom_data.get("metadata", {})
                if metadata.get("supplier"):
                    supplier_info = metadata["supplier"]
                    if isinstance(supplier_info, dict):
                        supplier = f"Organization: {supplier_info.get('name', 'Unknown')}"
                return name, str(version) if version else None, supplier

        # SPDX 3.0 format (spec-compliant @graph or legacy elements)
        elif "@graph" in sbom_data or (
            sbom_data.get("spdxVersion", "").startswith("SPDX-3.") and "elements" in sbom_data
        ):
            elements = sbom_data.get("@graph", sbom_data.get("elements", []))
            packages = [e for e in elements if e.get("type") == "software_Package"]
            if packages:
                pkg = packages[0]
                # Try to find the described package via relationships
                relationships = [e for e in elements if e.get("type") == "Relationship"]
                for rel in relationships:
                    if rel.get("relationshipType") == "describes":
                        target_ids = rel.get("to", [])
                        if target_ids:
                            for p in packages:
                                if p.get("spdxId") == target_ids[0]:
                                    pkg = p
                                    break
                name = pkg.get("name", "Unknown")
                version = pkg.get("software_packageVersion")
                supplier = None
                return name, version, supplier

        # SPDX 2.x format
        elif sbom_data.get("spdxVersion", "").startswith("SPDX-"):
            packages = sbom_data.get("packages", [])
            if packages:
                pkg = packages[0]
                doc_describes = sbom_data.get("documentDescribes", [])
                if doc_describes:
                    for p in packages:
                        if p.get("SPDXID") == doc_describes[0]:
                            pkg = p
                            break

                name = pkg.get("name", "Unknown")
                version = pkg.get("versionInfo")
                supplier = pkg.get("supplier")
                return name, version, supplier

        log.warning(f"Could not extract component info from {filename}")
        return None


class ReleaseSPDX30Builder(SPDX30Mixin, ReleaseSPDX3Builder):
    """SPDX 3.0 builder for releases."""

    pass


# =============================================================================
# Builder Factory
# =============================================================================


def default_version_for_format(output_format: SBOMFormat | str) -> SBOMVersion:
    """Single source of truth for the default SBOM version per output format.

    Used by ``get_sbom_builder`` (to pick a builder when no version is given) and
    by the aggregate-cache key resolution (``sboms.utils._resolve_output_version``)
    so the cache key and the actually-built version can never drift apart.
    """
    fmt = SBOMFormat(output_format) if isinstance(output_format, str) else output_format
    return SBOMVersion.CDX_1_6 if fmt == SBOMFormat.CYCLONEDX else SBOMVersion.SPDX_2_3


def get_sbom_builder(
    entity_type: str,
    output_format: SBOMFormat | str,
    version: SBOMVersion | str | None = None,
    entity: Any = None,
    user: Any = None,
) -> BaseSBOMBuilder:
    """
    Factory function to get the appropriate SBOM builder.

    Args:
        entity_type: Type of entity ("release"; "product" goes through ProductSBOMBuilder in utils.py)
        output_format: Output format (SBOMFormat.CYCLONEDX or SBOMFormat.SPDX)
        version: Format version (e.g., SBOMVersion.CDX_1_6, SBOMVersion.SPDX_2_3)
                 If None, defaults to latest version for the format
        entity: The entity to build SBOM for
        user: User for signed URL generation

    Returns:
        Appropriate builder instance

    Raises:
        ValueError: If unsupported format/version/entity_type combination
    """
    # Normalize format
    if isinstance(output_format, str):
        output_format = SBOMFormat(output_format.lower())

    # Normalize version and set defaults (shared with the aggregate cache key)
    if version is None:
        version = default_version_for_format(output_format)
    elif isinstance(version, str):
        version = SBOMVersion(version)

    builders: dict[tuple[str, SBOMFormat, SBOMVersion], type[BaseSBOMBuilder]] = {
        ("release", SBOMFormat.CYCLONEDX, SBOMVersion.CDX_1_6): ReleaseCycloneDX16Builder,
        ("release", SBOMFormat.CYCLONEDX, SBOMVersion.CDX_1_7): ReleaseCycloneDX17Builder,
        ("release", SBOMFormat.SPDX, SBOMVersion.SPDX_2_3): ReleaseSPDX23Builder,
        ("release", SBOMFormat.SPDX, SBOMVersion.SPDX_3_0): ReleaseSPDX30Builder,
    }

    key = (entity_type.lower(), output_format, version)
    builder_class = builders.get(key)

    if builder_class is None:
        supported = [f"{e}/{f.value}/{v.value}" for e, f, v in builders.keys()]
        raise ValueError(
            f"Unsupported combination: entity_type={entity_type}, format={output_format.value}, "
            f"version={version.value}. Supported: {supported}"
        )

    return builder_class(entity=entity, user=user)


def get_supported_output_formats() -> dict[str, list[str]]:
    """
    Get supported output format and version combinations.

    Returns:
        Dict mapping format names to list of supported versions
    """
    return {
        "cyclonedx": ["1.6", "1.7"],
        "spdx": ["2.3", "3.0"],
    }

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
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Protocol, TypeVar
from uuid import uuid4

from django.conf import settings
from django.utils import timezone

from sbomify.apps.core.models import Product, Project, Release
from sbomify.apps.sboms.sbom_format_schemas import cyclonedx_1_6 as cdx16
from sbomify.apps.sboms.sbom_format_schemas import cyclonedx_1_7 as cdx17
from sbomify.apps.sboms.sbom_format_schemas import spdx_2_3 as spdx23

log = logging.getLogger(__name__)


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


# Type variable for entity types
EntityT = TypeVar("EntityT", Project, Product, "Release")


class SBOMBuilderProtocol(Protocol):
    """Protocol defining the interface for SBOM builders."""

    def __call__(self, *args, **kwargs) -> Any:
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
            entity: The entity (project, product, or release) to build SBOM for
            user: User for signed URL generation
        """
        self.entity = entity
        self.user = user
        self.temp_files: list[Path] = []
        self.target_folder: Optional[Path] = None

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

    def __call__(self, *args, **kwargs) -> Any:
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

    def get_tool_info(self) -> dict:
        """Get common tool information for metadata."""
        return {
            "vendor": "sbomify, ltd",
            "name": "sbomify",
            "version": importlib.metadata.version("sbomify"),
        }

    def download_sbom_file(self, sbom) -> tuple[Path, str] | None:
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
            return None

    def select_best_sbom(self, sboms: list) -> Any:
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
    def cdx_module(self):
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
    def cdx_module(self):
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
    def cdx_module(self):
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

        sbom_artifacts = (
            release.artifacts.filter(sbom__isnull=False)
            .select_related("sbom__component", "sbom__component__team")
            .prefetch_related("sbom__component__team")
        )

        component_type_mapping = create_component_type_mapping()

        for artifact in sbom_artifacts:
            sbom_instance = artifact.sbom

            # Check access controls
            if release.product.is_public and not sbom_instance.component.is_public:
                continue

            sbom_result = self.download_sbom_file(sbom_instance)
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
            if not component_dict:
                log.warning(f"SBOM {sbom_path.name} missing component metadata")
                continue

            name, component_type, version = extract_component_info(component_dict)

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
    def spdx_module(self):
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
        sbom = {
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
        }

        # Add document describes relationship for the main package
        main_package_id = "SPDXRef-Package-Main"
        sbom["documentDescribes"] = [main_package_id]

        # Create main package representing the release
        main_package = {
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
        sbom_artifacts = (
            release.artifacts.filter(sbom__isnull=False)
            .select_related("sbom__component", "sbom__component__team")
            .prefetch_related("sbom__component__team")
        )

        package_index = 0
        for artifact in sbom_artifacts:
            sbom_instance = artifact.sbom

            # Check access controls
            if release.product.is_public and not sbom_instance.component.is_public:
                continue

            sbom_result = self.download_sbom_file(sbom_instance)
            if sbom_result is None:
                log.warning(f"SBOM for artifact {artifact.id} not found")
                continue

            sbom_path, sbom_id = sbom_result

            try:
                sbom_data = json.loads(sbom_path.read_text())
            except (json.JSONDecodeError, Exception) as e:
                log.error(f"Failed to read SBOM file {sbom_path.name}: {e}")
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

            # Add external reference to original SBOM
            from sbomify.apps.sboms.models import SBOM
            from sbomify.apps.sboms.utils import get_download_url_for_sbom

            try:
                original_sbom = SBOM.objects.get(id=sbom_id)
                download_url = get_download_url_for_sbom(original_sbom, self.user, settings.APP_BASE_URL)
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

        # Convert dict to Pydantic model for consistent serialization
        return spdx23.SPDXDocument.model_validate(sbom)

    def _extract_component_info_from_sbom(
        self, sbom_data: dict, filename: str
    ) -> tuple[str, str | None, str | None] | None:
        """
        Extract component info from either CycloneDX or SPDX source SBOM.

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

        # Try SPDX format
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
# Builder Factory
# =============================================================================


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
        entity_type: Type of entity ("project", "product", "release")
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

    # Normalize version and set defaults
    if version is None:
        if output_format == SBOMFormat.CYCLONEDX:
            version = SBOMVersion.CDX_1_6
        else:
            version = SBOMVersion.SPDX_2_3
    elif isinstance(version, str):
        version = SBOMVersion(version)

    # Builder registry
    builders = {
        ("release", SBOMFormat.CYCLONEDX, SBOMVersion.CDX_1_6): ReleaseCycloneDX16Builder,
        ("release", SBOMFormat.CYCLONEDX, SBOMVersion.CDX_1_7): ReleaseCycloneDX17Builder,
        ("release", SBOMFormat.SPDX, SBOMVersion.SPDX_2_3): ReleaseSPDX23Builder,
        # Project and Product builders can be added here following the same pattern
        # ("project", SBOMFormat.CYCLONEDX, SBOMVersion.CDX_1_6): ProjectCycloneDX16Builder,
        # ("product", SBOMFormat.CYCLONEDX, SBOMVersion.CDX_1_6): ProductCycloneDX16Builder,
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
        "spdx": ["2.3"],
    }

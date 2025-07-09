from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from django.conf import settings
from django.http import HttpRequest

from core.models import Component, Product, Project
from sboms.models import SBOM
from sboms.sbom_format_schemas import cyclonedx_1_5 as cdx15
from sboms.sbom_format_schemas import cyclonedx_1_6 as cdx16
from teams.models import Member, Team

from .versioning import CycloneDXSupportedVersion

log = logging.getLogger(__name__)


def verify_item_access(
    request: HttpRequest,
    item: Team | Product | Project | Component | SBOM,
    allowed_roles: list | None,
) -> bool:
    """
    Verify if the user has access to the item based on the allowed roles.
    """
    if not request.user.is_authenticated:
        return False

    team_id = None
    team_key = None

    if isinstance(item, Team):
        team_id = item.id
        team_key = item.key
    elif isinstance(item, (Product, Project, Component)):
        team_id = item.team_id
        team_key = item.team.key
    elif isinstance(item, SBOM):
        team_id = item.component.team_id
        team_key = item.component.team.key

    # Check session data first
    if team_key and "user_teams" in request.session:
        team_data = request.session["user_teams"].get(team_key)
        if team_data and "role" in team_data:
            # If no roles are specified, any role is allowed
            if allowed_roles is None:
                return True
            return team_data["role"] in allowed_roles

    # Fall back to database check
    if team_id:
        member = Member.objects.filter(user=request.user, team_id=team_id).first()
        if member:
            # If no roles are specified, any role is allowed
            if allowed_roles is None:
                return True
            return member.role in allowed_roles

    return False


@contextmanager
def temporary_sbom_files():
    """Context manager for handling temporary SBOM files with automatic cleanup."""
    temp_files = []
    try:
        yield temp_files
    finally:
        # Clean up all temporary files
        for temp_file in temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
                    log.debug(f"Cleaned up temporary file: {temp_file}")
            except Exception as e:
                log.warning(f"Failed to cleanup temporary file {temp_file}: {e}")


def validate_api_endpoint(sbom_id: str) -> bool:
    """
    Validate that the API endpoint for SBOM download exists and is accessible.

    Args:
        sbom_id: The SBOM ID to validate

    Returns:
        bool: True if the endpoint should be accessible, False otherwise
    """
    try:
        # Check if the SBOM exists and has proper access controls
        sbom = SBOM.objects.select_related("component").get(pk=sbom_id)

        # Verify the SBOM has a valid file
        if not sbom.sbom_filename:
            return False

        # Check if the component is public (for public API access)
        if not sbom.component.is_public:
            log.warning(f"API endpoint reference created for private SBOM {sbom_id}")

        return True
    except SBOM.DoesNotExist:
        log.error(f"API endpoint reference created for non-existent SBOM {sbom_id}")
        return False
    except Exception as e:
        # Handle database access issues gracefully (e.g., in tests)
        if "Database access not allowed" in str(e):
            log.debug(f"Database access not allowed for API endpoint validation of SBOM {sbom_id}")
            return True
        log.warning(f"Failed to validate API endpoint for SBOM {sbom_id}: {e}")
        return True  # Default to allowing the reference


def create_component_type_mapping() -> Dict[str, Any]:
    """Create mapping for component type strings to CycloneDX enums."""
    return {
        "application": cdx16.Type.application,
        "framework": cdx16.Type.framework,
        "library": cdx16.Type.library,
        "container": cdx16.Type.container,
        "platform": cdx16.Type.platform,
        "operating-system": cdx16.Type.operating_system,
        "device": cdx16.Type.device,
        "device-driver": cdx16.Type.device_driver,
        "firmware": cdx16.Type.firmware,
        "file": cdx16.Type.file,
        "machine-learning-model": cdx16.Type.machine_learning_model,
        "data": cdx16.Type.data,
        "cryptographic-asset": cdx16.Type.cryptographic_asset,
    }


def extract_component_info(component_dict: Dict[str, Any]) -> Tuple[str, str, Any]:
    """Extract basic component information from SBOM metadata."""
    name = component_dict.get("name", "unknown")
    component_type = component_dict.get("type", "library")
    version = component_dict.get("version")
    return name, component_type, version


def create_version_object(version: Any) -> Optional[cdx16.Version]:
    """Create a CycloneDX version object from various input types."""
    if not version:
        return None

    if isinstance(version, str):
        return cdx16.Version(version)
    elif isinstance(version, dict):
        return cdx16.Version(str(version))
    else:
        return cdx16.Version(str(version))


def create_external_reference(sbom_filename: str, sbom_id: str) -> cdx16.ExternalReference:
    """Create an external reference for the SBOM with proper validation."""
    # Validate the API endpoint exists
    if not validate_api_endpoint(sbom_id):
        log.warning(f"Creating external reference for potentially invalid SBOM endpoint: {sbom_id}")

    # Create hash of filename for reference
    filename_hash = hashlib.sha256(sbom_filename.encode("utf-8")).hexdigest()

    return cdx16.ExternalReference(
        type=cdx16.Type3.other,
        url=f"{settings.APP_BASE_URL}/api/v1/sboms/{sbom_id}/download",
        hashes=[cdx16.Hash(alg="SHA-256", content=cdx16.HashContent(filename_hash))],
    )


class ProjectSBOMBuilder:
    """
    Builds project SBOM from individual component SBOMs.

    This goes through all components and their associated SBOMs and
    creates a single SBOM for the project.

    The builder supports two usage patterns:
    - Initialize with project: ProjectSBOMBuilder(project).build(target_folder)
    - Pass project at build time: ProjectSBOMBuilder().build(project, target_folder)

    Sample output (CycloneDX 1.6):
    {
      "bomFormat": "CycloneDX",
      "specVersion": "1.6",
      "serialNumber": "urn:uuid:9d7b8a1b-7e1c-4c8e-bd9d-dee9b6f6f7f3",
      "version": 1,
      "metadata": {
        "timestamp": "2023-10-30T12:34:56Z",
        "tools": [
          {
            "vendor": "SBOMIFY",
            "name": "sbomify",
            "version": "0.0.1"
          }
        ]
      },
      "components": []
    }
    """

    def __init__(self, project: Project | None = None):
        self.project = project
        self.temp_files = []

    def __call__(self, *args, **kwargs) -> cdx16.CyclonedxSoftwareBillOfMaterialsStandard:
        # Support both (target_folder) and (project, target_folder)
        if len(args) == 1 and hasattr(self, "project") and self.project:
            target_folder = args[0]
            project = self.project
        elif len(args) == 2:
            project, target_folder = args
            self.project = project
        else:
            raise TypeError("ProjectSBOMBuilder.__call__() expects (target_folder) or (project, target_folder)")

        self.target_folder = target_folder

        # Use context manager for automatic cleanup
        with temporary_sbom_files() as temp_files:
            self.temp_files = temp_files
            return self._build_sbom(project)

    def _build_sbom(self, project: Project) -> cdx16.CyclonedxSoftwareBillOfMaterialsStandard:
        """Build the SBOM with proper database optimization and cleanup."""
        self.sbom = cdx16.CyclonedxSoftwareBillOfMaterialsStandard(bomFormat="CycloneDX", specVersion="1.6")
        self.sbom.field_schema = "http://cyclonedx.org/schema/bom-1.6.schema.json"
        self.sbom.serialNumber = f"urn:uuid:{uuid4()}"
        self.sbom.version = 1

        # metadata section
        self.sbom.metadata = cdx16.Metadata(
            timestamp=datetime.now(timezone.utc),
            tools=[
                cdx16.Tool(
                    vendor="sbomify, ltd",
                    name="sbomify",
                    version=importlib.metadata.version("sbomify"),
                    externalReferences=[
                        cdx16.ExternalReference(type=cdx16.Type3.website, url="https://sbomify.com"),
                        cdx16.ExternalReference(type=cdx16.Type3.vcs, url="https://github.com/sbomify/sbomify"),
                    ],
                )
            ],
            component=cdx16.Component(name=project.name, type=cdx16.Type.application, scope=cdx16.Scope.required),
        )

        # components section - only include public components
        self.sbom.components = []

        # DATABASE OPTIMIZATION: Use select_related and prefetch_related to avoid N+1 queries
        public_components = (
            project.projectcomponent_set.select_related("component", "component__team")
            .prefetch_related("component__sbom_set")
            .filter(component__is_public=True)
        )

        for pc in public_components:
            # Double-check component is public for extra security
            if not pc.component.is_public:
                log.warning(f"Skipping private component {pc.component.id} in public SBOM aggregation")
                continue

            sbom_result = self.download_component_sbom(pc.component)
            if sbom_result is None:
                log.warning(f"SBOM for public component {pc.component.id} not found")
                continue

            sbom_path, sbom_id = sbom_result
            log.info(f"Downloaded SBOM for public component {pc.component.id} to {sbom_path}")

            try:
                sbom_data = json.loads(sbom_path.read_text())
            except json.JSONDecodeError as e:
                log.error(f"Invalid JSON in SBOM file {sbom_path.name}: {e}")
                continue
            except Exception as e:
                log.error(f"Failed to read SBOM file {sbom_path.name}: {e}")
                continue

            component = self.get_component_metadata(sbom_path.name, sbom_data, sbom_id)
            if component is None:
                log.warning(f"Failed to get component from SBOM {sbom_path}")
                continue

            self.sbom.components.append(component)

        return self.sbom

    def download_component_sbom(self, component: Component) -> tuple[Path, str] | None:
        """Download the SBOM file for a component with proper cleanup tracking.

        Args:
            component: The component to download SBOM for

        Returns:
            Tuple of (Path to the downloaded SBOM file, SBOM ID), or None if no SBOM found
        """
        from core.object_store import S3Client

        # Use the prefetched SBOMs to avoid additional queries
        sboms = list(component.sbom_set.all())

        # TODO: For now, we download the first SBOM.
        # In the future, we need to support multiple SBOMs for a single component
        # and pick the latest/appropriate one.

        if not sboms:
            return None

        sbom = sboms[0]

        # Download SBOM data from S3
        s3_client = S3Client("SBOMS")
        try:
            sbom_data = s3_client.get_sbom_data(sbom.sbom_filename)
            download_path = self.target_folder / sbom.sbom_filename
            download_path.write_bytes(sbom_data)

            # Track file for cleanup
            self.temp_files.append(download_path)

            return download_path, str(sbom.id)
        except Exception as e:
            log.warning(f"Failed to download SBOM {sbom.sbom_filename}: {e}")
            return None

    def get_component_metadata(self, sbom_filename: str, sbom_data: dict, sbom_id: str) -> cdx16.Component | None:
        """Get component metadata from SBOM and create a CycloneDX 1.6 component that references the original."""
        # Validate basic SBOM format
        if not self._validate_sbom_format(sbom_filename, sbom_data):
            return None

        component_dict = sbom_data.get("metadata", {}).get("component")
        if not component_dict:
            log.warning(f"SBOM {sbom_filename} does not contain component metadata")
            return None

        # Extract component information
        name, component_type, version = extract_component_info(component_dict)

        # Create CycloneDX component
        return self._create_cyclonedx_component(name, component_type, version, sbom_filename, sbom_id)

    def _validate_sbom_format(self, sbom_filename: str, sbom_data: dict) -> bool:
        """Validate that the SBOM is in CycloneDX format."""
        if sbom_data.get("bomFormat") != "CycloneDX":
            log.warning(f"SBOM {sbom_filename} is not in CycloneDX format")
            return False
        return True

    def _create_cyclonedx_component(
        self, name: str, component_type: str, version: Any, sbom_filename: str, sbom_id: str
    ) -> Optional[cdx16.Component]:
        """Create a CycloneDX 1.6 component with proper error handling."""
        try:
            component_type_mapping = create_component_type_mapping()

            # Create the CycloneDX 1.6 component with proper enum values
            component = cdx16.Component(
                name=name,
                type=component_type_mapping.get(component_type, cdx16.Type.library),  # Default to library
                scope=cdx16.Scope.required,
            )

            # Add version if present
            version_obj = create_version_object(version)
            if version_obj:
                component.version = version_obj

            # Add external reference to the original SBOM
            component.externalReferences = [create_external_reference(sbom_filename, sbom_id)]

            return component

        except Exception as e:
            spec_version = "unknown"
            log.warning(f"Failed to create CycloneDX 1.6 component from {spec_version} SBOM {sbom_filename}: {e}")
            return None


class ProductSBOMBuilder:
    """
    Builds product SBOM from all component SBOMs across all projects.

    This goes through all projects in a product, then all components in each project,
    and their associated SBOMs to create a single aggregated SBOM for the entire product.

    The product SBOM includes all components from all projects with proper external
    references to the original component SBOMs.
    """

    def __init__(self, product: Product | None = None):
        self.product = product
        self.temp_files = []

    def __call__(self, *args, **kwargs) -> cdx16.CyclonedxSoftwareBillOfMaterialsStandard:
        # Support both (target_folder) and (product, target_folder)
        if len(args) == 1 and hasattr(self, "product") and self.product:
            target_folder = args[0]
            product = self.product
        elif len(args) == 2:
            product, target_folder = args
            self.product = product
        else:
            raise TypeError("ProductSBOMBuilder.__call__() expects (target_folder) or (product, target_folder)")

        self.target_folder = target_folder

        # Use context manager for automatic cleanup
        with temporary_sbom_files() as temp_files:
            self.temp_files = temp_files
            return self._build_sbom(product)

    def _build_sbom(self, product: Product) -> cdx16.CyclonedxSoftwareBillOfMaterialsStandard:
        """Build the product SBOM with proper database optimization and cleanup."""
        self.sbom = cdx16.CyclonedxSoftwareBillOfMaterialsStandard(bomFormat="CycloneDX", specVersion="1.6")
        self.sbom.field_schema = "http://cyclonedx.org/schema/bom-1.6.schema.json"
        self.sbom.serialNumber = f"urn:uuid:{uuid4()}"
        self.sbom.version = 1

        # metadata section
        self.sbom.metadata = cdx16.Metadata(
            timestamp=datetime.now(timezone.utc),
            tools=[
                cdx16.Tool(
                    vendor="sbomify, ltd",
                    name="sbomify",
                    version=importlib.metadata.version("sbomify"),
                    externalReferences=[
                        cdx16.ExternalReference(type=cdx16.Type3.website, url="https://sbomify.com"),
                        cdx16.ExternalReference(type=cdx16.Type3.vcs, url="https://github.com/sbomify/sbomify"),
                    ],
                )
            ],
            component=cdx16.Component(name=product.name, type=cdx16.Type.application, scope=cdx16.Scope.required),
        )

        # components section - aggregate all components from all PUBLIC projects
        self.sbom.components = []

        # DATABASE OPTIMIZATION: Use select_related and prefetch_related to avoid N+1 queries
        public_projects = (
            product.projects.select_related("team")
            .prefetch_related(
                "projectcomponent_set__component",
                "projectcomponent_set__component__team",
                "projectcomponent_set__component__sbom_set",
            )
            .filter(is_public=True)
        )

        for project in public_projects:
            # Double-check project is public for extra security
            if not project.is_public:
                log.warning(f"Skipping private project {project.id} in public SBOM aggregation")
                continue

            log.info(f"Processing public project {project.name} for product {product.name}")
            self._process_project_components(project)

        return self.sbom

    def _process_project_components(self, project: Project) -> None:
        """Process all public components within a project."""
        # SECURITY: Only process public components within public projects
        public_components = [pc for pc in project.projectcomponent_set.all() if pc.component.is_public]

        for pc in public_components:
            # Double-check component is public for extra security
            if not pc.component.is_public:
                log.warning(f"Skipping private component {pc.component.id} in public SBOM aggregation")
                continue

            sbom_result = self.download_component_sbom(pc.component)
            if sbom_result is None:
                log.warning(f"SBOM for public component {pc.component.id} not found")
                continue

            sbom_path, sbom_id = sbom_result
            log.info(f"Downloaded SBOM for public component {pc.component.id} to {sbom_path}")

            try:
                sbom_data = json.loads(sbom_path.read_text())
            except json.JSONDecodeError as e:
                log.error(f"Invalid JSON in SBOM file {sbom_path.name}: {e}")
                continue
            except Exception as e:
                log.error(f"Failed to read SBOM file {sbom_path.name}: {e}")
                continue

            component = self.get_component_metadata(sbom_path.name, sbom_data, project.name, sbom_id)
            if component is None:
                log.warning(f"Failed to get component from SBOM {sbom_path}")
                continue

            self.sbom.components.append(component)

    def download_component_sbom(self, component: Component) -> tuple[Path, str] | None:
        """Download the SBOM file for a component with proper cleanup tracking.

        Args:
            component: The component to download SBOM for

        Returns:
            Tuple of (Path to the downloaded SBOM file, SBOM ID), or None if no SBOM found
        """
        from core.object_store import S3Client

        # Use the prefetched SBOMs to avoid additional queries
        sboms = list(component.sbom_set.all())

        # TODO: For now, we download the first SBOM.
        # In the future, we need to support multiple SBOMs for a single component
        # and pick the latest/appropriate one.

        if not sboms:
            return None

        sbom = sboms[0]

        # Download SBOM data from S3
        s3_client = S3Client("SBOMS")
        try:
            sbom_data = s3_client.get_sbom_data(sbom.sbom_filename)
            download_path = self.target_folder / sbom.sbom_filename
            download_path.write_bytes(sbom_data)

            # Track file for cleanup
            self.temp_files.append(download_path)

            return download_path, str(sbom.id)
        except Exception as e:
            log.warning(f"Failed to download SBOM {sbom.sbom_filename}: {e}")
            return None

    def get_component_metadata(
        self, sbom_filename: str, sbom_data: dict, project_name: str, sbom_id: str
    ) -> cdx16.Component | None:
        """Get component metadata from SBOM and create a CycloneDX 1.6 component that references the original."""
        # Validate basic SBOM format
        if not self._validate_sbom_format(sbom_filename, sbom_data):
            return None

        component_dict = sbom_data.get("metadata", {}).get("component")
        if not component_dict:
            log.warning(f"SBOM {sbom_filename} does not contain component metadata")
            return None

        # Extract component information
        name, component_type, version = extract_component_info(component_dict)

        # Add project context to the component name for better traceability
        component_display_name = f"{project_name}/{name}" if project_name else name

        # Create CycloneDX component
        return self._create_cyclonedx_component(component_display_name, component_type, version, sbom_filename, sbom_id)

    def _validate_sbom_format(self, sbom_filename: str, sbom_data: dict) -> bool:
        """Validate that the SBOM is in CycloneDX format."""
        if sbom_data.get("bomFormat") != "CycloneDX":
            log.warning(f"SBOM {sbom_filename} is not in CycloneDX format")
            return False
        return True

    def _create_cyclonedx_component(
        self, name: str, component_type: str, version: Any, sbom_filename: str, sbom_id: str
    ) -> Optional[cdx16.Component]:
        """Create a CycloneDX 1.6 component with proper error handling."""
        try:
            component_type_mapping = create_component_type_mapping()

            # Create the CycloneDX 1.6 component with proper enum values
            component = cdx16.Component(
                name=name,
                type=component_type_mapping.get(component_type, cdx16.Type.library),  # Default to library
                scope=cdx16.Scope.required,
            )

            # Add version if present
            version_obj = create_version_object(version)
            if version_obj:
                component.version = version_obj

            # Add external reference to the original SBOM
            component.externalReferences = [create_external_reference(sbom_filename, sbom_id)]

            return component

        except Exception as e:
            spec_version = "unknown"
            log.warning(f"Failed to create CycloneDX 1.6 component from {spec_version} SBOM {sbom_filename}: {e}")
            return None


class ReleaseSBOMBuilder:
    """
    Builds release SBOM from specific artifacts included in the release.

    This goes through only the SBOM artifacts that are explicitly included in a release
    and creates a single aggregated SBOM that represents the exact state of that release.

    Unlike ProductSBOMBuilder or ProjectSBOMBuilder, this only includes the specific
    artifacts that have been selected for the release, not all available artifacts.
    """

    def __init__(self, release=None):
        self.release = release
        self.temp_files = []

    def __call__(self, *args, **kwargs):
        # Support both (target_folder) and (release, target_folder)
        if len(args) == 1 and hasattr(self, "release") and self.release:
            target_folder = args[0]
            release = self.release
        elif len(args) == 2:
            release, target_folder = args
            self.release = release
        else:
            raise TypeError("ReleaseSBOMBuilder.__call__() expects (target_folder) or (release, target_folder)")

        self.target_folder = target_folder

        # Use context manager for automatic cleanup
        with temporary_sbom_files() as temp_files:
            self.temp_files = temp_files
            return self._build_sbom(release)

    def _build_sbom(self, release):
        """Build the release SBOM with proper database optimization and cleanup."""
        self.sbom = cdx16.CyclonedxSoftwareBillOfMaterialsStandard(bomFormat="CycloneDX", specVersion="1.6")
        self.sbom.field_schema = "http://cyclonedx.org/schema/bom-1.6.schema.json"
        self.sbom.serialNumber = f"urn:uuid:{uuid4()}"
        self.sbom.version = 1

        # metadata section
        self.sbom.metadata = cdx16.Metadata(
            timestamp=datetime.now(timezone.utc),
            tools=[
                cdx16.Tool(
                    vendor="sbomify, ltd",
                    name="sbomify",
                    version=importlib.metadata.version("sbomify"),
                    externalReferences=[
                        cdx16.ExternalReference(type=cdx16.Type3.website, url="https://sbomify.com"),
                        cdx16.ExternalReference(type=cdx16.Type3.vcs, url="https://github.com/sbomify/sbomify"),
                    ],
                )
            ],
            component=cdx16.Component(
                name=f"{release.product.name} - {release.name}", type=cdx16.Type.application, scope=cdx16.Scope.required
            ),
        )

        # components section - only include artifacts specifically in this release
        self.sbom.components = []

        # Get all SBOM artifacts in this release
        sbom_artifacts = (
            release.artifacts.filter(sbom__isnull=False)
            .select_related("sbom__component")
            .prefetch_related("sbom__component__team")
        )

        for artifact in sbom_artifacts:
            sbom = artifact.sbom

            # Skip if component/product access restrictions apply
            if not self._should_include_artifact(release, sbom):
                continue

            sbom_result = self.download_specific_sbom(sbom)
            if sbom_result is None:
                log.warning(f"SBOM for artifact {artifact.id} (SBOM {sbom.id}) not found")
                continue

            sbom_path, sbom_id = sbom_result
            log.info(f"Downloaded SBOM for release artifact {artifact.id} to {sbom_path}")

            try:
                sbom_data = json.loads(sbom_path.read_text())
            except json.JSONDecodeError as e:
                log.error(f"Invalid JSON in SBOM file {sbom_path.name}: {e}")
                continue
            except Exception as e:
                log.error(f"Failed to read SBOM file {sbom_path.name}: {e}")
                continue

            component = self.get_component_metadata(sbom_path.name, sbom_data, release.name, sbom_id)
            if component is None:
                log.warning(f"Failed to get component from SBOM {sbom_path}")
                continue

            self.sbom.components.append(component)

        return self.sbom

    def _should_include_artifact(self, release, sbom) -> bool:
        """Check if an SBOM artifact should be included based on access controls."""
        # For public products/releases, only include public components
        if release.product.is_public:
            return sbom.component.is_public

        # For private products, include all artifacts in the release
        # (access control is handled at the release level)
        return True

    def download_specific_sbom(self, sbom) -> tuple[Path, str] | None:
        """Download a specific SBOM artifact with proper cleanup tracking.

        Args:
            sbom: The specific SBOM instance to download

        Returns:
            Tuple of (Path to the downloaded SBOM file, SBOM ID), or None if not found
        """
        from core.object_store import S3Client

        if not sbom.sbom_filename:
            return None

        # Download SBOM data from S3
        s3_client = S3Client("SBOMS")
        try:
            sbom_data = s3_client.get_sbom_data(sbom.sbom_filename)
            download_path = self.target_folder / sbom.sbom_filename
            download_path.write_bytes(sbom_data)

            # Track file for cleanup
            self.temp_files.append(download_path)

            return download_path, str(sbom.id)
        except Exception as e:
            log.warning(f"Failed to download SBOM {sbom.sbom_filename}: {e}")
            return None

    def get_component_metadata(
        self, sbom_filename: str, sbom_data: dict, release_name: str, sbom_id: str
    ) -> cdx16.Component | None:
        """Get component metadata from SBOM and create a CycloneDX 1.6 component that references the original."""
        # Validate basic SBOM format
        if not self._validate_sbom_format(sbom_filename, sbom_data):
            return None

        component_dict = sbom_data.get("metadata", {}).get("component")
        if not component_dict:
            log.warning(f"SBOM {sbom_filename} does not contain component metadata")
            return None

        # Extract component information
        name, component_type, version = extract_component_info(component_dict)

        # Add release context to the component name for better traceability
        component_display_name = f"{release_name}/{name}" if release_name != "latest" else name

        # Create CycloneDX component
        return self._create_cyclonedx_component(component_display_name, component_type, version, sbom_filename, sbom_id)

    def _validate_sbom_format(self, sbom_filename: str, sbom_data: dict) -> bool:
        """Validate that the SBOM is in CycloneDX format."""
        if sbom_data.get("bomFormat") != "CycloneDX":
            log.warning(f"SBOM {sbom_filename} is not in CycloneDX format")
            return False
        return True

    def _create_cyclonedx_component(
        self, name: str, component_type: str, version: Any, sbom_filename: str, sbom_id: str
    ) -> Optional[cdx16.Component]:
        """Create a CycloneDX 1.6 component with proper error handling."""
        try:
            component_type_mapping = create_component_type_mapping()

            # Create the CycloneDX 1.6 component with proper enum values
            component = cdx16.Component(
                name=name,
                type=component_type_mapping.get(component_type, cdx16.Type.library),  # Default to library
                scope=cdx16.Scope.required,
            )

            # Add version if present
            version_obj = create_version_object(version)
            if version_obj:
                component.version = version_obj

            # Add external reference to the original SBOM
            component.externalReferences = [create_external_reference(sbom_filename, sbom_id)]

            return component

        except Exception as e:
            spec_version = "unknown"
            log.warning(f"Failed to create CycloneDX 1.6 component from {spec_version} SBOM {sbom_filename}: {e}")
            return None


def get_project_sbom_package(project: Project, target_folder: Path) -> Path:
    """
    Generates the project SBOM file.

    SECURITY: Only generates SBOMs for public projects to prevent leaking private SBOMs.

    Args:
        project: The project to generate the SBOM for
        target_folder: The folder to save the SBOM to

    Returns:
        Path to the generated SBOM file

    Raises:
        PermissionError: If the project is not public
    """
    # SECURITY: Only allow SBOM generation for public projects
    if not project.is_public:
        raise PermissionError(f"Cannot generate SBOM for private project {project.id}")

    builder = ProjectSBOMBuilder(project)
    sbom = builder(target_folder)

    # Save project SBOM with clean serialization (exclude null values)
    sbom_path = target_folder / f"{project.name}.cdx.json"
    sbom_path.write_text(sbom.model_dump_json(indent=2, exclude_none=True, exclude_unset=True))

    return sbom_path


def get_product_sbom_package(product: Product, target_folder: Path) -> Path:
    """
    Generates the aggregated product SBOM file using the latest release.

    This function now delegates to the latest release instead of arbitrarily
    selecting SBOMs. It ensures we get a consistent, curated set of artifacts
    that represent the current state of the product.

    SECURITY: Only generates SBOMs for public products to prevent leaking private SBOMs.

    Args:
        product: The product to generate the SBOM for
        target_folder: The folder to save the SBOM to

    Returns:
        Path to the generated SBOM file

    Raises:
        PermissionError: If the product is not public
    """
    # SECURITY: Only allow SBOM generation for public products
    if not product.is_public:
        raise PermissionError(f"Cannot generate SBOM for private product {product.id}")

    # Import here to avoid circular imports
    from core.models import Release

    # Get or create the latest release for this product
    latest_release = Release.get_or_create_latest_release(product)

    # Use ReleaseSBOMBuilder to create the SBOM from the latest release
    builder = ReleaseSBOMBuilder(latest_release)
    sbom = builder(target_folder)

    # Save product SBOM with clean serialization (exclude null values)
    sbom_path = target_folder / f"{product.name}.cdx.json"
    sbom_path.write_text(sbom.model_dump_json(indent=2, exclude_none=True, exclude_unset=True))

    return sbom_path


def get_release_sbom_package(release, target_folder: Path) -> Path:
    """
    Generates the release-specific SBOM file.

    SECURITY: Only generates SBOMs for public releases to prevent leaking private SBOMs.

    Args:
        release: The release to generate the SBOM for
        target_folder: The folder to save the SBOM to

    Returns:
        Path to the generated SBOM file

    Raises:
        PermissionError: If the release's product is not public
    """
    # SECURITY: Only allow SBOM generation for public product releases
    if not release.product.is_public:
        raise PermissionError(f"Cannot generate SBOM for private product release {release.id}")

    # Use ReleaseSBOMBuilder to create release-specific SBOM
    builder = ReleaseSBOMBuilder(release)
    sbom = builder(target_folder)

    # Save release SBOM with clean serialization (exclude null values)
    sbom_path = target_folder / f"{release.product.name}-{release.name}.cdx.json"
    sbom_path.write_text(sbom.model_dump_json(indent=2, exclude_none=True, exclude_unset=True))

    return sbom_path


def get_cyclonedx_module(spec_version: CycloneDXSupportedVersion) -> ModuleType:
    """Get the appropriate CycloneDX module for the given version.

    Args:
        spec_version: The CycloneDX version to get the module for

    Returns:
        The appropriate CycloneDX module
    """
    module_map: dict[CycloneDXSupportedVersion, ModuleType] = {
        CycloneDXSupportedVersion.v1_5: cdx15.CyclonedxSoftwareBillOfMaterialsStandard,
        CycloneDXSupportedVersion.v1_6: cdx16.CyclonedxSoftwareBillOfMaterialsStandard,
    }
    return module_map[spec_version]


def create_default_component_metadata(user, team_id: int, custom_metadata: dict = None) -> dict:
    """
    Create default metadata for a component.

    Args:
        user: The user creating the component
        team_id: The team ID
        custom_metadata: Optional custom metadata to merge with defaults

    Returns:
        dict: The component metadata
    """
    from allauth.socialaccount.models import SocialAccount

    # Get user and team information
    social_account = SocialAccount.objects.filter(user=user, provider="keycloak").first()
    user_metadata = social_account.extra_data.get("user_metadata", {}) if social_account else {}

    # Only populate if we have actual user metadata
    default_metadata = {}

    # Only add supplier info if we have company data from Keycloak
    company_name = user_metadata.get("company")
    if company_name:
        supplier_url = user_metadata.get("supplier_url")
        default_metadata["supplier"] = {"name": company_name, "url": [supplier_url] if supplier_url else None}
        default_metadata["organization"] = {
            "name": company_name,
            "contact": {
                "name": f"{user.first_name} {user.last_name}".strip(),
                "email": user.email,
            },
        }

    # Add author and supplier info if we have a real user name and email
    if user.first_name and user.last_name and user.email:
        user_name = f"{user.first_name} {user.last_name}".strip()

        default_metadata["authors"] = [
            {
                "name": user_name,
                "email": user.email,
            }
        ]

        # If no company-specific supplier was set above, use user info
        if "supplier" not in default_metadata:
            default_metadata["supplier"] = {"name": user_name, "url": None}

    # If custom metadata is provided, merge it with defaults
    if custom_metadata:
        component_metadata = custom_metadata.copy()

        # Add default author/organization info if not provided
        if "authors" not in component_metadata:
            component_metadata["authors"] = default_metadata["authors"]

        if "organization" not in component_metadata:
            component_metadata["organization"] = default_metadata["organization"]

        if "supplier" not in component_metadata:
            component_metadata["supplier"] = default_metadata["supplier"]

        return component_metadata

    return default_metadata

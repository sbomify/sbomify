from __future__ import annotations

import importlib.metadata
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from django.http import HttpRequest

from sbomify import logging
from teams.models import Member, Team

from .models import SBOM, Component, Product, Project
from .sbom_format_schemas import cyclonedx_1_5 as cdx15
from .sbom_format_schemas import cyclonedx_1_6 as cdx16
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
        if project:
            self.sboms = SBOM.objects.filter(component__projectcomponent__project=project)

    def __call__(self, *args, **kwargs) -> cdx16.CyclonedxSoftwareBillOfMaterialsStandard:
        # Support both (target_folder) and (project, target_folder)
        if len(args) == 1 and hasattr(self, "project") and self.project:
            target_folder = args[0]
            project = self.project
        elif len(args) == 2:
            project, target_folder = args
            self.project = project
            self.sboms = SBOM.objects.filter(component__projectcomponent__project=project)
        else:
            raise TypeError("ProjectSBOMBuilder.__call__() expects (target_folder) or (project, target_folder)")

        self.target_folder = target_folder
        self.sbom = cdx16.CyclonedxSoftwareBillOfMaterialsStandard(bomFormat="CycloneDX", specVersion="1.6")
        self.sbom.field_schema = "http://cyclonedx.org/schema/bom-1.6.schema.json"
        self.sbom.serialNumber = f"urn:uuid:{uuid4()}"
        self.sbom.version = 1

        # metadata section
        self.sbom.metadata = cdx16.Metadata(
            timestamp=datetime.now(timezone.utc),
            tools=[
                cdx16.Tool(
                    vendor="SBOMIFY",
                    name="sbomify",
                    version=importlib.metadata.version("sbomify"),
                )
            ],
            component=cdx16.Component(name=project.name, type="application"),
        )

        # components section
        self.sbom.components = []
        for pc in project.projectcomponent_set.all():
            sbom_path = self.download_component_sbom(pc.component)
            log.info(f"Downloaded SBOM for component {pc.component.id} to {sbom_path}")
            if sbom_path is None:
                log.warning(f"SBOM for component {pc.component.id} not found")
                continue

            try:
                sbom_data = json.loads(sbom_path.read_text())
            except json.JSONDecodeError as e:
                log.error(f"Invalid JSON in SBOM file {sbom_path.name}: {e}")
                continue
            except Exception as e:
                log.error(f"Failed to read SBOM file {sbom_path.name}: {e}")
                continue

            component = self.get_component_metadata(sbom_path.name, sbom_data)
            if component is None:
                log.warning(f"Failed to get component from SBOM {sbom_path}")
                continue

            self.sbom.components.append(component)

        return self.sbom

    def download_component_sbom(self, component: Component) -> Path | None:
        """Download the SBOM file for a component.

        Args:
            component: The component to download SBOM for

        Returns:
            Path to the downloaded SBOM file, or None if no SBOM found
        """
        from core.object_store import S3Client

        sboms = component.sboms.all()

        # TODO: For now, we download the first SBOM.
        # In the future, we need to support multiple SBOMs for a single component
        # and pick the latest/appropriate one.

        if sboms.count() == 0:
            return None

        sbom = sboms.first()

        # Download SBOM data from S3
        s3_client = S3Client("SBOMS")
        try:
            sbom_data = s3_client.get_sbom_data(sbom.sbom_filename)
            download_path = self.target_folder / sbom.sbom_filename
            download_path.write_bytes(sbom_data)
            return download_path
        except Exception as e:
            log.warning(f"Failed to download SBOM {sbom.sbom_filename}: {e}")
            return None

    def get_component_metadata(self, sbom_filename: str, sbom_data: dict) -> cdx15.Component | cdx16.Component | None:
        """Get component metadata from SBOM."""
        if sbom_data.get("bomFormat") != "CycloneDX":
            log.warning(f"SBOM {sbom_filename} is not in CycloneDX format")
            return None

        component_dict = sbom_data.get("metadata", {}).get("component")
        if not component_dict:
            log.warning(f"SBOM {sbom_filename} does not contain component metadata")
            return None

        if sbom_data["specVersion"] == "1.6":
            component = cdx16.Component.model_validate(component_dict)
        elif sbom_data["specVersion"] == "1.5":
            component = cdx15.Component.model_validate(component_dict)
        else:
            log.warning(f"Unsupported CycloneDX specVersion {sbom_data['specVersion']} for {sbom_filename}")
            return None

        if component:
            component.externalReferences = [
                cdx16.ExternalReference(
                    type=cdx16.ExternalReferenceType.other,
                    url=f"https://sbomify.io/sboms/{sbom_filename}",
                    hashes=[cdx16.Hash(alg="SHA-256", content=sbom_filename.removesuffix(".json"))],
                )
            ]

        return component


def get_project_sbom_package(project: Project, target_folder: Path) -> Path:
    """
    Generates a ZIP package containing the project SBOM and all component SBOMs.

    Args:
        project: The project to generate the SBOM package for
        target_folder: The folder to save the package to

    Returns:
        Path to the generated ZIP package
    """
    builder = ProjectSBOMBuilder(project)
    sbom = builder(target_folder)

    # Save project SBOM
    sbom_path = target_folder / f"{project.name}.cdx.json"
    sbom_path.write_text(sbom.model_dump_json(indent=2))

    # Create ZIP package
    zip_path = target_folder / f"{project.name}.cdx.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # Add project SBOM
        zip_file.write(sbom_path, sbom_path.name)

        # Add all component SBOMs
        for file_path in target_folder.glob("*.json"):
            if file_path != sbom_path:  # Don't add the project SBOM twice
                zip_file.write(file_path, file_path.name)

    return zip_path  # Return the zip file path instead of sbom_path


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

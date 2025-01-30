import importlib.metadata
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from django.http import HttpRequest

from core.object_store import S3Client
from core.utils import token_to_number
from sbomify import logging
from teams.models import Member, Team

from .models import SBOM, Component, Product, Project
from .sbom_format_schemas import cyclonedx_1_5 as cdx15
from .sbom_format_schemas import cyclonedx_1_6 as cdx16

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

    if isinstance(item, Team):
        team_id = item.id

    elif isinstance(item, (Product, Project, Component)):
        team_id = item.team_id

    elif isinstance(item, SBOM):
        team_id = item.component.team_id

    user_teams = request.session.get("user_teams", {})

    if user_teams:
        for team_key, team_data in user_teams.items():
            if token_to_number(team_key) == team_id:
                if allowed_roles is not None and team_data["role"] not in allowed_roles:
                    return False

                return True

        return False

    # If here then it's personal access token based auth so no user teams present in session
    member = Member.objects.filter(user=request.user, team_id=team_id).first()
    if member is None:
        return False

    if allowed_roles is not None and member.role not in allowed_roles:
        return False

    return True


class ProjectSBOMBuilder:
    """
    Class to build SBOM for a project.

    The generated SBOM contains all the components of the project. Components are added to the components
    section of the SBOM and contain external references to the SBOMs of the components.

    "components": [
        {
        "type": "library",
        "group": "org.example",
        "name": "persistence",
        "version": "5.2.0",
        "externalReferences": [
            {
            "type": "bom",
            "url": "urn:cdx:bdd819e6-ee8f-42d7-a4d0-166ff44d51e8/5",
            "comment": "Refers to version 5 of a specific BOM. Integrity verification should be performed "
                       "to ensure the BOM has not been tampered with.",
            "hashes": [
                {
                "alg": "SHA-512",
                "content": "45c6e3d03ec4207234e926063c484446d8b55f4bfce3f929f44cbc2320565290cc4b71de70c1d98379"
                           "2c6d63504f47f6b94513d09847dbae69c8f7cdd51ce980"
                }
            ]
            }
        ]
        }
    ]
    """

    def __call__(self, project: Project, target_folder: Path) -> cdx16.CyclonedxSoftwareBillOfMaterialsStandard:
        self.project = project
        self.target_folder = target_folder
        self.sbom = cdx16.CyclonedxSoftwareBillOfMaterialsStandard(bomFormat="CycloneDX", specVersion="1.6")
        self.sbom.field_schema = "http://cyclonedx.org/schema/bom-1.6.schema.json"
        self.sbom.version = 1
        self.sbom.serialNumber = "urn:uuid:" + str(uuid4())

        self.sbom.metadata = cdx16.Metadata(
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            tools=dict(
                components=[
                    cdx16.Component(
                        publisher="sbomify",
                        name="sbomify",
                        type="application",
                        version=importlib.metadata.version("sbomify"),
                    )
                ]
            ),
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

            component = self.get_component_from_sbom_metadata(sbom_path)
            if component is None:
                log.warning(f"Failed to get component from SBOM {sbom_path}")
                continue

            self.sbom.components.append(component)

        if not self.sbom.components:
            self.sbom.components = None

        return self.sbom

    def download_component_sbom(self, component: Component) -> Path | None:
        s3 = S3Client("SBOMS")

        sbom = component.latest_sbom

        if sbom:
            download_path = self.target_folder / sbom.sbom_filename
            data = s3.get_sbom_data(sbom.sbom_filename)
            with open(download_path, "wb") as f:
                f.write(data)

            return download_path

        return None

    def get_component_from_sbom_metadata(self, sbom_filename: Path) -> cdx16.Component | cdx15.Component | None:
        sbom_data = json.loads(sbom_filename.read_text())
        component = None
        if sbom_data["bomFormat"] != "CycloneDX":
            log.warning(f"SBOM {sbom_filename} is not in CycloneDX format")
            return None

        component_dict = sbom_data.get("metadata", {}).get("component")
        if component_dict is None:
            log.warning(f"SBOM {sbom_filename} does not contain component metadata")
            return None

        if sbom_data["specVersion"] == "1.6":
            component = cdx16.Component.model_validate(component_dict)

        elif sbom_data["specVersion"] == "1.5":
            component = cdx15.Component.model_validate(component_dict)

        if component:
            component.externalReferences = [
                cdx16.ExternalReference(
                    type="bom",
                    url=f"urn:cdx:bdd819e6-ee8f-42d7-a4d0-166ff44d51e8/{component.version}",
                    comment=f"SBOM file: {sbom_filename.name}",
                    hashes=[cdx16.Hash(alg="SHA-256", content=sbom_filename.name.removesuffix(".json"))],
                )
            ]

        return component


def get_project_sbom_package(project: Project, target_folder: Path) -> Path:
    sbom = ProjectSBOMBuilder()(project, target_folder)

    sbom_filename = f"{project.name}.cdx.json"
    sbom_path = target_folder / sbom_filename
    with open(sbom_path, "w") as f:
        f.write(
            sbom.model_dump_json(
                exclude_defaults=True, exclude_unset=True, exclude_none=True, serialize_as_any=True, indent=2
            )
        )

    # Create zip file containing all files in target_folder
    zip_path = target_folder / f"{project.name}.cdx.zip"
    with zipfile.ZipFile(zip_path, "w") as zip_file:
        for file_path in target_folder.iterdir():
            if file_path != zip_path:  # Don't include the zip file itself
                zip_file.write(file_path, file_path.name)

    return zip_path  # Return the zip file path instead of sbom_path

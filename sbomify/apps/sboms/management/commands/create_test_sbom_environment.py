import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.http import HttpRequest

from sbomify.apps.core.object_store import S3Client
from sbomify.apps.sboms.apis import sbom_upload_cyclonedx, sbom_upload_spdx
from sbomify.apps.sboms.models import SBOM, Component, Product, ProductProject, Project, ProjectComponent
from sbomify.apps.sboms.schemas import SPDXSchema, cdx15, cdx16
from sbomify.apps.teams.models import Team


class Command(BaseCommand):
    help = "Creates a test environment with products, projects, components and SBOM data"

    def __init__(self):
        super().__init__()
        self.s3 = S3Client(bucket_type="SBOMS")
        self.sbom_bucket = settings.AWS_SBOMS_STORAGE_BUCKET_NAME

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-key",
            type=str,
            help="Workspace key to create the test environment for (flag name retained for compatibility).",
        )
        parser.add_argument(
            "--clean",
            action="store_true",
            help="Clean up existing test data before creating new environment",
        )

    def handle(self, *args, **options):
        team_key = options.get("team_key")
        clean = options.get("clean")

        # Get or create team
        if team_key:
            team = Team.objects.get(key=team_key)
        else:
            team = Team.objects.first()
            if not team:
                self.stdout.write(self.style.ERROR("No workspace found. Please create a workspace first."))
                return

        # Clean up existing test data if requested
        if clean:
            self.cleanup_test_data(team)
            return  # Exit after cleanup

        # Create test environment
        with transaction.atomic():
            self.create_test_environment(team)

    def cleanup_test_data(self, team):
        """Clean up existing test data for the workspace"""
        self.stdout.write(f"Cleaning up existing test data for workspace {team.key}...")

        # Get all test products for this workspace
        test_products = Product.objects.filter(team=team, name__startswith="test-product")
        self.stdout.write(f"Found {test_products.count()} test products to delete")

        # Get all test projects for this workspace
        test_projects = Project.objects.filter(team=team, name__startswith="test-project")
        self.stdout.write(f"Found {test_projects.count()} test projects to delete")

        # Get all test components for this workspace
        test_components = Component.objects.filter(team=team, name__startswith="test-component-")
        self.stdout.write(f"Found {test_components.count()} test components to delete")

        # Get all SBOMs for test components
        test_sboms = SBOM.objects.filter(component__in=test_components)
        self.stdout.write(f"Found {test_sboms.count()} test SBOMs to delete")

        # Delete SBOM files from S3
        for sbom in test_sboms:
            try:
                # Check if object exists before trying to delete
                try:
                    self.s3.s3.Object(self.sbom_bucket, sbom.sbom_filename).load()
                    self.s3.delete_object(self.sbom_bucket, sbom.sbom_filename)
                    self.stdout.write(f"Deleted SBOM file from S3: {sbom.sbom_filename}")
                except ClientError as e:
                    if e.response["Error"]["Code"] == "404":
                        self.stdout.write(f"SBOM file not found in S3: {sbom.sbom_filename}")
                    else:
                        raise
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Failed to delete SBOM file {sbom.sbom_filename}: {str(e)}"))

        # Delete all test data in the correct order to handle foreign key constraints
        if test_sboms.exists():
            test_sboms.delete()
            self.stdout.write("Deleted test SBOMs from database")

        if test_components.exists():
            test_components.delete()
            self.stdout.write("Deleted test components from database")

        if test_projects.exists():
            test_projects.delete()
            self.stdout.write("Deleted test projects from database")

        if test_products.exists():
            test_products.delete()
            self.stdout.write("Deleted test products from database")

        self.stdout.write(self.style.SUCCESS("Cleanup completed successfully"))

    def create_test_environment(self, team):
        """Create the test environment with all necessary data"""
        self.stdout.write("Creating test environment...")

        # Create test product
        product = Product.objects.create(team=team, name="test-product", is_public=True)
        self.stdout.write(self.style.SUCCESS(f"Created product: {product.name}"))

        # Create test project
        project = Project.objects.create(
            team=team, name="test-project", is_public=True, metadata={"description": "Test project for SBOM testing"}
        )
        self.stdout.write(self.style.SUCCESS(f"Created project: {project.name}"))

        # Link project to product
        ProductProject.objects.create(product=product, project=project)
        self.stdout.write(self.style.SUCCESS("Linked project to product"))

        # Group SBOM files by source
        sbom_groups = {
            "hello-world-syft": ["hello-world_syft.spdx.json", "hello-world_syft.cdx.json"],
            "sbomify-syft": ["sbomify_syft.spdx.json", "sbomify_syft.cdx.json"],
            "sbomify-syft-parlay": ["sbomify_syft_parlay.spdx.json", "sbomify_syft_parlay.cdx.json"],
            "sbomify-trivy": ["sbomify_trivy.spdx.json", "sbomify_trivy.cdx.json"],
            "sbomify-trivy-parlay": ["sbomify_trivy_parlay.spdx.json", "sbomify_trivy_parlay.cdx.json"],
            "protobom": ["protobom-v0.5.2.spdx.json"],
        }

        for source_name, sbom_files in sbom_groups.items():
            # Create component for this source
            component = Component.objects.create(
                team=team,
                name=f"test-component-{source_name}",
                is_public=True,
                metadata={"type": "library", "language": "python", "source": source_name},
            )
            self.stdout.write(self.style.SUCCESS(f"Created component: {component.name}"))

            # Link component to project
            ProjectComponent.objects.create(project=project, component=component)
            self.stdout.write(self.style.SUCCESS(f"Linked component {component.name} to project"))

            # Create SBOMs for this component
            for sbom_file in sbom_files:
                sbom_path = Path(__file__).parent.parent.parent / "tests" / "test_data" / sbom_file
                self.stdout.write(f"Loading SBOM from: {sbom_path}")
                if not sbom_path.exists():
                    self.stdout.write(self.style.ERROR(f"SBOM file not found: {sbom_path}"))
                    continue

                with open(sbom_path, "rb") as f_raw:
                    sbom_raw_data = f_raw.read()

                with open(sbom_path) as f_json:
                    sbom_data_dict = json.load(f_json)

                # Prepare mock request for API call
                mock_request = MagicMock(spec=HttpRequest)
                mock_request.body = sbom_raw_data
                mock_request.user = MagicMock()  # Simulate an authenticated user
                mock_request.session = MagicMock()  # Simulate a session

                format_type = ""

                # Patch verify_item_access for the duration of the API call
                with patch("sbomify.apps.sboms.apis.verify_item_access", return_value=True):
                    if "spdxVersion" in sbom_data_dict:
                        format_type = "spdx"
                        self.stdout.write(f"Processing {format_type.upper()} SBOM: {sbom_file}")
                        try:
                            payload = SPDXSchema(**sbom_data_dict)
                            status_code, response_data = sbom_upload_spdx(mock_request, component.id, payload)
                            if status_code == 201:
                                sbom_id = response_data.get("id")
                                success_msg = f"API call successful for {sbom_file}, SBOM ID: {sbom_id}"
                                self.stdout.write(self.style.SUCCESS(success_msg))
                            else:
                                error_msg = (
                                    f"API call failed for {sbom_file}: Status {status_code}, Response: {response_data}"
                                )
                                self.stdout.write(self.style.ERROR(error_msg))
                        except Exception as e:
                            self.stdout.write(self.style.ERROR(f"Error processing SPDX {sbom_file} via API: {e}"))
                            continue

                    else:  # CycloneDX
                        format_type = "cyclonedx"
                        self.stdout.write(f"Processing {format_type.upper()} SBOM: {sbom_file}")
                        try:
                            spec_version = sbom_data_dict.get("specVersion", "1.5")
                            if spec_version == "1.5":
                                payload = cdx15.CyclonedxSoftwareBillOfMaterialsStandard(**sbom_data_dict)
                            elif spec_version == "1.6":
                                payload = cdx16.CyclonedxSoftwareBillOfMaterialsStandard(**sbom_data_dict)
                            else:
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"Unsupported CycloneDX specVersion {spec_version} for {sbom_file}"
                                    )
                                )
                                continue

                            status_code, response_data = sbom_upload_cyclonedx(mock_request, component.id, payload)
                            if status_code == 201:
                                sbom_id = response_data.get("id")
                                success_msg = f"API call successful for {sbom_file}, SBOM ID: {sbom_id}"
                                self.stdout.write(self.style.SUCCESS(success_msg))
                            else:
                                error_msg = (
                                    f"API call failed for {sbom_file}: Status {status_code}, Response: {response_data}"
                                )
                                self.stdout.write(self.style.ERROR(error_msg))
                        except Exception as e:
                            self.stdout.write(self.style.ERROR(f"Error processing CycloneDX {sbom_file} via API: {e}"))
                            continue

                # Removed manual SBOM object creation, S3 upload, and task triggering.
                # The API functions (sbom_upload_spdx/sbom_upload_cyclonedx) now handle this.

                if format_type:  # Only print if format_type was set (i.e., processing happened)
                    success_msg = (
                        f"Successfully processed {format_type.upper()} SBOM for component {component.name} via API call"
                    )
                    self.stdout.write(self.style.SUCCESS(success_msg))

        self.stdout.write(self.style.SUCCESS("Test environment created successfully!"))

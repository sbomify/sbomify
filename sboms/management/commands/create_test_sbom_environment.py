import json
from pathlib import Path

from botocore.exceptions import ClientError
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core.object_store import S3Client
from sboms.models import SBOM, Component, Product, ProductProject, Project, ProjectComponent
from teams.models import Team


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
            help="Team key to create the test environment for. If not provided, will use the first team found.",
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
                self.stdout.write(self.style.ERROR("No team found. Please create a team first."))
                return

        # Clean up existing test data if requested
        if clean:
            self.cleanup_test_data(team)
            return  # Exit after cleanup

        # Create test environment
        with transaction.atomic():
            self.create_test_environment(team)

    def cleanup_test_data(self, team):
        """Clean up existing test data for the team"""
        self.stdout.write(f"Cleaning up existing test data for team {team.key}...")

        # Get all test products for this team
        test_products = Product.objects.filter(team=team, name__startswith="test-product")
        self.stdout.write(f"Found {test_products.count()} test products to delete")

        # Get all test projects for this team
        test_projects = Project.objects.filter(team=team, name__startswith="test-project")
        self.stdout.write(f"Found {test_projects.count()} test projects to delete")

        # Get all test components for this team
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
            "hello-world": ["hello-world-sbom_spdx.json", "hello-world-sbom_cyclonedx.json"],
            "sbomify": ["sbomify_spdx.json", "sbomify_cyclonedx.json"],
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
                # Load and create SBOM from test data
                sbom_path = Path(__file__).parent.parent.parent / "tests" / "test_data" / sbom_file
                self.stdout.write(f"Loading SBOM from: {sbom_path}")
                if not sbom_path.exists():
                    self.stdout.write(self.style.ERROR(f"SBOM file not found: {sbom_path}"))
                    continue

                with open(sbom_path) as f:
                    sbom_data = json.load(f)

                # Determine format and version
                if "spdxVersion" in sbom_data:
                    format_type = "spdx"
                    format_version = sbom_data["spdxVersion"].removeprefix("SPDX-")
                    name = sbom_data.get("name", f"{source_name}-component")
                    version = sbom_data.get("packages", [{}])[0].get("versionInfo", "1.0.0")
                    licenses = [pkg.get("licenseConcluded", "NOASSERTION") for pkg in sbom_data.get("packages", [])]
                else:  # CycloneDX
                    format_type = "cyclonedx"
                    format_version = sbom_data.get("specVersion", "1.5")
                    name = sbom_data.get("metadata", {}).get("component", {}).get("name", f"{source_name}-component")
                    version = sbom_data.get("metadata", {}).get("component", {}).get("version", "1.0.0")
                    licenses = []
                    for comp in sbom_data.get("components", []):
                        if "licenses" in comp:
                            for license_info in comp["licenses"]:
                                if "license" in license_info:
                                    if "id" in license_info["license"]:
                                        licenses.append(license_info["license"]["id"])
                                    elif "name" in license_info["license"]:
                                        licenses.append(license_info["license"]["name"])

                # Create SBOM record
                SBOM.objects.create(
                    name=name,
                    version=version,
                    format=format_type,
                    format_version=format_version,
                    licenses=licenses,
                    sbom_filename=sbom_file,
                    source=source_name,
                    component=component,
                )

                # Upload SBOM file to S3
                with open(sbom_path, "rb") as f:
                    self.s3.upload_data_as_file(self.sbom_bucket, sbom_file, f.read())

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created and uploaded {format_type.upper()} SBOM for component {component.name}"
                    )
                )

        self.stdout.write(self.style.SUCCESS("Test environment created successfully!"))

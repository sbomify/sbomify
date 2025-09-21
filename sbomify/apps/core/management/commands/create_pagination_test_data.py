import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.http import HttpRequest

from sbomify.apps.core.models import Component
from sbomify.apps.sboms.apis import sbom_upload_cyclonedx, sbom_upload_spdx
from sbomify.apps.sboms.schemas import SPDXSchema, cdx15, cdx16
from sbomify.apps.teams.models import Team

User = get_user_model()


class Command(BaseCommand):
    help = "Creates 100 SBOMs for pagination testing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            type=str,
            default="ssmith",
            help="Username to create test data for (default: ssmith)",
        )
        parser.add_argument(
            "--count",
            type=int,
            default=100,
            help="Number of SBOMs to create (default: 100)",
        )

    def handle(self, *args, **options):
        username = options["username"]
        count = options["count"]

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User '{username}' not found"))
            return

        # Get the user's team
        team = Team.objects.filter(member__user=user).first()
        if not team:
            self.stdout.write(self.style.ERROR(f"User '{username}' is not a member of any team"))
            return

        self.stdout.write(f"Creating {count} SBOMs for user '{username}' in team '{team.name}'...")

        # Find or create a test component
        component_name = "pagination-test-component"
        component, created = Component.objects.get_or_create(
            name=component_name,
            team=team,
            defaults={
                "component_type": "sbom",
                "is_public": True,
                "metadata": {"description": "Component for pagination testing"},
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f"Created component: {component.name}"))
        else:
            self.stdout.write(f"Using existing component: {component.name}")

        # Available test SBOM files
        test_files = [
            "hello-world_syft.cdx.json",
            "hello-world_syft.spdx.json",
            "sbomify_syft.cdx.json",
            "sbomify_syft.spdx.json",
            "sbomify_trivy.cdx.json",
            "sbomify_trivy.spdx.json",
            "protobom-v0.5.2.spdx.json",
        ]

        created_count = 0
        with transaction.atomic():
            for i in range(count):
                # Cycle through test files
                test_file = test_files[i % len(test_files)]
                sbom_path = Path(__file__).parent.parent.parent.parent / "sboms" / "tests" / "test_data" / test_file

                if not sbom_path.exists():
                    self.stdout.write(self.style.WARNING(f"Test file not found: {sbom_path}"))
                    continue

                try:
                    with open(sbom_path) as f_json:
                        sbom_data_dict = json.load(f_json)

                    # Modify the SBOM name to make it unique
                    if "spdxVersion" in sbom_data_dict:
                        # SPDX format
                        sbom_data_dict["name"] = f"test-sbom-{i + 1:03d}-{test_file.replace('.json', '')}"
                        if "documentName" in sbom_data_dict:
                            sbom_data_dict["documentName"] = sbom_data_dict["name"]
                    else:
                        # CycloneDX format
                        if "metadata" not in sbom_data_dict:
                            sbom_data_dict["metadata"] = {}
                        if "component" not in sbom_data_dict["metadata"]:
                            sbom_data_dict["metadata"]["component"] = {}
                        sbom_data_dict["metadata"]["component"]["name"] = (
                            f"test-sbom-{i + 1:03d}-{test_file.replace('.json', '')}"
                        )

                    # Prepare mock request for API call
                    mock_request = MagicMock(spec=HttpRequest)
                    mock_request.body = json.dumps(sbom_data_dict).encode()
                    mock_request.user = user
                    mock_request.session = MagicMock()

                    # Upload SBOM via API
                    with patch("sbomify.apps.sboms.apis.verify_item_access", return_value=True):
                        if "spdxVersion" in sbom_data_dict:
                            # SPDX format
                            payload = SPDXSchema(**sbom_data_dict)
                            status_code, response_data = sbom_upload_spdx(mock_request, component.id, payload)
                        else:
                            # CycloneDX format
                            spec_version = sbom_data_dict.get("specVersion", "1.5")
                            if spec_version == "1.5":
                                payload = cdx15.CyclonedxSoftwareBillOfMaterialsStandard(**sbom_data_dict)
                            elif spec_version == "1.6":
                                payload = cdx16.CyclonedxSoftwareBillOfMaterialsStandard(**sbom_data_dict)
                            else:
                                self.stdout.write(self.style.WARNING(f"Unsupported CycloneDX version: {spec_version}"))
                                continue
                            status_code, response_data = sbom_upload_cyclonedx(mock_request, component.id, payload)

                        if status_code == 201:
                            created_count += 1
                            if created_count % 10 == 0:  # Progress update every 10 SBOMs
                                self.stdout.write(f"Created {created_count}/{count} SBOMs...")
                        else:
                            self.stdout.write(
                                self.style.WARNING(f"Failed to create SBOM {i + 1}: Status {status_code}")
                            )

                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"Error creating SBOM {i + 1}: {e}"))
                    continue

        self.stdout.write(
            self.style.SUCCESS(f"Successfully created {created_count} SBOMs for component '{component.name}'")
        )
        self.stdout.write(
            f"You can now test pagination by visiting the components page at /components/ "
            f"or the component details page at /component/{component.id}/"
        )

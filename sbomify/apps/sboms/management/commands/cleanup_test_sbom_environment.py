from django.core.management.base import BaseCommand
from django.db import transaction

from sbomify.apps.sboms.models import Component, Product, Project
from sbomify.apps.teams.models import Team


class Command(BaseCommand):
    help = "Cleans up test environments created by create_test_sbom_environment"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=str,
            help="Workspace ID to clean up test data for (flag name retained for compatibility).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )

    def handle(self, *args, **options):
        team_id = options.get("team_id")
        dry_run = options.get("dry_run")

        if team_id:
            teams = [Team.objects.get(id=team_id)]
        else:
            teams = Team.objects.all()

        for team in teams:
            self.cleanup_team_data(team, dry_run)

    def cleanup_team_data(self, team, dry_run):
        """Clean up test data for a specific workspace"""
        self.stdout.write(f"\nCleaning up test data for workspace: {team.name}")

        # Get counts before deletion
        components = Component.objects.filter(team=team, name__startswith="test-component-")
        projects = Project.objects.filter(team=team, name__startswith="test-project")
        products = Product.objects.filter(team=team, name__startswith="test-product")

        if dry_run:
            self.stdout.write("Would delete:")
            self.stdout.write(f"  - {components.count()} test components")
            self.stdout.write(f"  - {projects.count()} test projects")
            self.stdout.write(f"  - {products.count()} test products")
            return

        with transaction.atomic():
            # Delete all SBOMs for test components (this will cascade delete the SBOMs)
            deleted_components = components.delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_components[0]} test components"))

            # Delete all test projects
            deleted_projects = projects.delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_projects[0]} test projects"))

            # Delete all test products
            deleted_products = products.delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_products[0]} test products"))

        self.stdout.write(self.style.SUCCESS(f"Cleanup completed for workspace: {team.name}"))

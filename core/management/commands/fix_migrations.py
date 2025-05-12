from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder


class Command(BaseCommand):
    help = "Fixes migration history by ensuring migrations are applied in the correct order"

    def handle(self, *args, **options):
        with transaction.atomic():
            try:
                # Try to load migrations to check for consistency
                loader = MigrationLoader(connection)
                loader.check_consistent_history(connection)
                self.stdout.write(self.style.SUCCESS("Migration history is consistent"))
                return
            except InconsistentMigrationHistory as e:
                self.stdout.write(self.style.WARNING(f"Found inconsistent migration history: {e}"))

            # Only proceed with fixes if we found inconsistencies
            recorder = MigrationRecorder(connection)
            Migration = recorder.Migration

            # Get all applied migrations
            applied_migrations = set(Migration.objects.values_list("app", "name"))

            # Track migrations we've fixed to avoid duplicate fixes
            fixed_migrations = set()

            # Check each migration's dependencies
            for app_label, migration_name in applied_migrations:
                if (app_label, migration_name) in fixed_migrations:
                    continue

                migration = loader.get_migration(app_label, migration_name)
                if not migration:
                    continue

                # Check each dependency
                for dep_app, dep_name in migration.dependencies:
                    dep_key = (dep_app, dep_name)
                    if dep_key not in applied_migrations:
                        self.stdout.write(
                            f"Found inconsistent migration: {app_label}.{migration_name} "
                            f"is applied before its dependency {dep_app}.{dep_name}"
                        )

                        # Remove the migration that was applied too early
                        Migration.objects.filter(app=app_label, name=migration_name).delete()
                        fixed_migrations.add((app_label, migration_name))
                        self.stdout.write(
                            self.style.SUCCESS(f"Removed {app_label}.{migration_name} to fix dependency order")
                        )
                        break  # Stop checking other dependencies once we've fixed this migration

import sys

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Fixes migration history by ensuring socialaccount migrations are applied in the correct order"

    def handle(self, *args, **options):
        try:
            # Try to acquire a lock
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT pg_try_advisory_lock(12345)")
                if not cursor.fetchone()[0]:
                    self.stdout.write(self.style.ERROR("Another migration process is running"))
                    sys.exit(1)
            except OperationalError:
                self.stdout.write(self.style.WARNING("Could not acquire lock, proceeding anyway"))

            with transaction.atomic():
                recorder = MigrationRecorder(connection)
                Migration = recorder.Migration

                # Check all dependencies
                dependencies = [("sites", "0001_initial"), ("core", "__first__")]
                for app, name in dependencies:
                    if name == "__first__":
                        if not Migration.objects.filter(app=app).exists():
                            self.stdout.write(self.style.ERROR(f"{app} migrations must be applied first"))
                            return
                    else:
                        if not Migration.objects.filter(app=app, name=name).exists():
                            self.stdout.write(self.style.ERROR(f"{app}.{name} must be applied first"))
                            return

                # Verify all required tables exist
                required_tables = [
                    "socialaccount_socialaccount",
                    "socialaccount_socialapp",
                    "socialaccount_socialtoken",
                ]
                for table in required_tables:
                    cursor.execute(
                        """
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_schema = 'public'
                            AND table_name = %s
                        );
                    """,
                        [table],
                    )
                    if not cursor.fetchone()[0]:
                        self.stdout.write(self.style.ERROR(f"Required table {table} does not exist"))
                        return

                # Fake all socialaccount migrations in order
                migrations = [
                    "0001_initial",
                    "0002_token_max_lengths",
                    "0003_extra_data_default_dict",
                    "0004_app_provider_id_settings",
                    "0005_socialtoken_nullable_app",
                    "0006_alter_socialaccount_extra_data",
                ]

                # Check current state
                existing_migrations = set(Migration.objects.filter(app="socialaccount").values_list("name", flat=True))
                self.stdout.write(f"Found {len(existing_migrations)} existing socialaccount migrations")

                # Store original state for rollback
                original_migrations = set(existing_migrations)

                # Apply migrations in order
                for migration in migrations:
                    if migration not in existing_migrations:
                        self.stdout.write(f"Faking socialaccount.{migration}...")
                        try:
                            call_command("migrate", "socialaccount", migration, "--fake")
                            self.stdout.write(self.style.SUCCESS(f"Successfully faked socialaccount.{migration}"))
                        except Exception as e:
                            # Rollback any faked migrations
                            if existing_migrations != original_migrations:
                                self.stdout.write("Rolling back faked migrations...")
                                Migration.objects.filter(
                                    app="socialaccount", name__in=existing_migrations - original_migrations
                                ).delete()
                            self.stdout.write(self.style.ERROR(f"Failed to fake socialaccount.{migration}: {str(e)}"))
                            raise
                    else:
                        self.stdout.write(f"socialaccount.{migration} already applied")

                # Verify final state
                final_migrations = set(Migration.objects.filter(app="socialaccount").values_list("name", flat=True))
                if final_migrations == set(migrations):
                    self.stdout.write(self.style.SUCCESS("All socialaccount migrations are now properly applied"))
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Migration state mismatch. Expected {set(migrations)}, got {final_migrations}"
                        )
                    )

        except OperationalError as e:
            self.stdout.write(self.style.ERROR(f"Database error: {str(e)}"))
            sys.exit(1)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Unexpected error: {str(e)}"))
            sys.exit(1)
        finally:
            # Release the lock
            try:
                cursor.execute("SELECT pg_advisory_unlock(12345)")
            except OperationalError:
                pass

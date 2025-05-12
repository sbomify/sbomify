from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder


class Command(BaseCommand):
    help = "Fixes migration history by removing all socialaccount migrations to fix dependency order"

    def handle(self, *args, **options):
        with transaction.atomic():
            recorder = MigrationRecorder(connection)
            Migration = recorder.Migration

            # Remove all socialaccount migrations
            socialaccount_migrations = Migration.objects.filter(app="socialaccount")
            if socialaccount_migrations.exists():
                self.stdout.write("Removing all socialaccount migrations to fix dependency order...")
                socialaccount_migrations.delete()
                self.stdout.write(self.style.SUCCESS("Successfully removed all socialaccount migrations"))
            else:
                self.stdout.write("No socialaccount migrations found - nothing to fix")

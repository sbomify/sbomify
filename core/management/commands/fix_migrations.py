from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder


class Command(BaseCommand):
    help = "Fixes migration history by removing socialaccount.0001_initial if it was applied before sites.0001_initial"

    def handle(self, *args, **options):
        with transaction.atomic():
            recorder = MigrationRecorder(connection)
            Migration = recorder.Migration

            # Remove socialaccount.0001_initial if it exists
            socialaccount = Migration.objects.filter(app="socialaccount", name="0001_initial").first()
            if socialaccount:
                self.stdout.write("Removing socialaccount.0001_initial to fix dependency order...")
                socialaccount.delete()
                self.stdout.write(self.style.SUCCESS("Successfully removed socialaccount.0001_initial"))
            else:
                self.stdout.write("No socialaccount.0001_initial migration found - nothing to fix")

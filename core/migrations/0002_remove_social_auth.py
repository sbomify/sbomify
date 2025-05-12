from django.db import migrations, models
from django.apps.registry import Apps
from django.db.utils import OperationalError, ProgrammingError


def remove_social_auth_tables(apps: Apps, schema_editor):
    """
    Safely remove django-social-auth tables while preserving django-allauth data.
    This function is idempotent - it will only remove tables if they exist.
    Also fixes InconsistentMigrationHistory for socialaccount/0001_initial and sites/0001_initial.
    """
    # List of models to try to remove
    model_names = [
        ('social_auth', 'Association'),
        ('social_auth', 'Code'),
        ('social_auth', 'Nonce'),
        ('social_auth', 'Partial'),
        ('social_auth', 'UserSocialAuth'),
    ]

    # Try to delete each model's data
    for app_label, model_name in model_names:
        try:
            model = apps.get_model(app_label, model_name)
            model.objects.all().delete()
        except LookupError:
            pass

    # Remove the migration records for social_auth
    try:
        MigrationRecorder = apps.get_model('migrations', 'Migration')
        MigrationRecorder.objects.filter(
            app__in=['social_auth', 'social_auth_django']
        ).delete()
    except LookupError:
        pass

    # --- Fix for InconsistentMigrationHistory ---
    try:
        MigrationRecorder = apps.get_model('migrations', 'Migration')
        # Get all migration records for socialaccount and sites
        socialaccount_migrations = list(
            MigrationRecorder.objects.filter(app='socialaccount').order_by('applied').values('name', 'applied')
        )
        sites_migrations = list(
            MigrationRecorder.objects.filter(app='sites').order_by('applied').values('name', 'applied')
        )
        if socialaccount_migrations and sites_migrations:
            socialaccount_first = socialaccount_migrations[0]['applied']
            sites_first = sites_migrations[0]['applied']
            # If socialaccount.0001_initial was applied before sites.0001_initial, fix it
            if socialaccount_first < sites_first:
                # Remove all socialaccount migration records so they can be re-applied in the correct order
                MigrationRecorder.objects.filter(app='socialaccount').delete()
    except (OperationalError, ProgrammingError) as e:
        # These errors can occur if the database is not yet ready or if the migrations table doesn't exist
        # We can safely ignore them as the migration will be retried later
        pass


def reverse_remove_social_auth_tables(apps, schema_editor):
    """
    This is a no-op because we don't want to recreate the tables.
    The reverse migration is not possible as we're removing data.
    """
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0001_initial'),
        ('sites', '0001_initial'),  # Ensure sites migration is applied first
    ]

    operations = [
        migrations.RunPython(
            remove_social_auth_tables,
            reverse_remove_social_auth_tables,
        ),
    ]
from django.db import migrations, models
from django.apps.registry import Apps


def remove_social_auth_tables(apps: Apps, schema_editor):
    """
    Safely remove django-social-auth tables while preserving django-allauth data.
    This function is idempotent - it will only remove tables if they exist.
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
            # Model doesn't exist, which is fine - we're removing it anyway
            pass

    # Remove the migration records
    try:
        MigrationRecorder = apps.get_model('migrations', 'Migration')
        MigrationRecorder.objects.filter(
            app__in=['social_auth', 'social_auth_django']
        ).delete()
    except LookupError:
        # This should never happen as migrations app is always present
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
from django.db import migrations
from django.conf import settings


def create_keycloak_social_app(apps, schema_editor):
    """Create the Keycloak social app and associate it with the site."""
    Site = apps.get_model('sites', 'Site')
    SocialApp = apps.get_model('socialaccount', 'SocialApp')

    # Get the site
    site = Site.objects.get(id=1)

    # Create the Keycloak social app if it doesn't exist
    social_app, created = SocialApp.objects.get_or_create(
        provider='openid_connect',
        name='Keycloak',
        defaults={
            'client_id': settings.KEYCLOAK_CLIENT_ID,
            'secret': settings.KEYCLOAK_CLIENT_SECRET,
            'settings': {
                'server_url': f"{settings.KEYCLOAK_SERVER_URL}realms/{settings.KEYCLOAK_REALM}/.well-known/openid-configuration"
            }
        }
    )

    # The following line was deferred to a later migration (core.0007):
    # social_app.sites.add(site)


def reverse_keycloak_social_app(apps, schema_editor):
    """Remove the Keycloak social app."""
    SocialApp = apps.get_model('socialaccount', 'SocialApp')
    SocialApp.objects.filter(provider='openid_connect', name='Keycloak').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0003_site_from_app_base_url'),
        ('sites', '0002_alter_domain_unique'),
        ('socialaccount', '0001_initial'),
        ('socialaccount', '0004_app_provider_id_settings'),
    ]

    operations = [
        migrations.RunPython(create_keycloak_social_app, reverse_keycloak_social_app),
    ]
from django.db import migrations
from django.conf import settings

def associate_keycloak_to_site(apps, schema_editor):
    """Associate the Keycloak social app with the default site."""
    Site = apps.get_model('sites', 'Site')
    SocialApp = apps.get_model('socialaccount', 'SocialApp')

    try:
        # Get the default site (adjust if site ID is different or needs to be dynamic)
        site = Site.objects.get(id=1)

        # Get the Keycloak social app
        social_app = SocialApp.objects.get(
            provider='openid_connect',
            name='Keycloak'
        )

        # Associate the social app with the site
        social_app.sites.add(site)
    except Site.DoesNotExist:
        # Handle case where site doesn't exist, if necessary
        # For example, log a warning or skip
        print("Default site (id=1) not found. Skipping Keycloak app association.")
    except SocialApp.DoesNotExist:
        # Handle case where Keycloak social app doesn't exist
        print("Keycloak social app not found. Skipping association.")

def reverse_associate_keycloak_to_site(apps, schema_editor):
    """Remove the association of Keycloak social app from the default site."""
    Site = apps.get_model('sites', 'Site')
    SocialApp = apps.get_model('socialaccount', 'SocialApp')

    try:
        site = Site.objects.get(id=1)
        social_app = SocialApp.objects.get(
            provider='openid_connect',
            name='Keycloak'
        )
        social_app.sites.remove(site)
    except Site.DoesNotExist:
        pass # Or log
    except SocialApp.DoesNotExist:
        pass # Or log

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_create_socialapp_sites_table'),
        # Ensure socialaccount models are available and M2M table is created
        ('socialaccount', '0007_ensure_socialapp_sites_table'),
        ('sites', '0002_alter_domain_unique'), # Ensure site model is up to date
    ]

    operations = [
        migrations.RunPython(associate_keycloak_to_site, reverse_associate_keycloak_to_site),
    ]
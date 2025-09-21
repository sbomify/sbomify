from django.conf import settings
from django.db import migrations
import os
from urllib.parse import urlparse

def get_domain_from_url(url):
    parsed = urlparse(url)
    return parsed.netloc

def create_or_update_site(apps, schema_editor):
    Site = apps.get_model('sites', 'Site')
    app_base_url = os.environ.get('APP_BASE_URL', 'localhost:8000')
    domain = get_domain_from_url(app_base_url)
    name = domain.split(':')[0] if ':' in domain else domain
    site, created = Site.objects.get_or_create(id=1, defaults={"domain": domain, "name": name})
    if not created:
        site.domain = domain
        site.name = name
        site.save()

def reverse_func(apps, schema_editor):
    # No-op: don't delete the site
    pass

class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("sites", "0002_alter_domain_unique"),
    ]
    operations = [
        migrations.RunPython(create_or_update_site, reverse_func),
    ]
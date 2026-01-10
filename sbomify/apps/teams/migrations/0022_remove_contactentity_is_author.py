# Generated manually for CycloneDX Contact Profile Alignment - Part 2

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0021_cyclonedx_contact_alignment'),
    ]

    operations = [
        # Remove is_author field from ContactEntity (separate migration for PostgreSQL)
        migrations.RemoveField(
            model_name='contactentity',
            name='is_author',
        ),
    ]

    # For reverse migration, the field will be added back automatically by Django


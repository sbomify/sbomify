# Generated manually for CycloneDX Contact Profile Alignment - Part 1

import django.db.models.deletion
from django.db import migrations, models

import sbomify.apps.core.utils


def migrate_authors_forward(apps, schema_editor):
    """Migrate author entity contacts to AuthorContact model."""
    ContactEntity = apps.get_model('teams', 'ContactEntity')
    ContactProfileContact = apps.get_model('teams', 'ContactProfileContact')
    AuthorContact = apps.get_model('teams', 'AuthorContact')

    for entity in ContactEntity.objects.filter(is_author=True):
        # Migrate contacts from author entities to AuthorContact
        for contact in ContactProfileContact.objects.filter(entity=entity):
            AuthorContact.objects.create(
                id=sbomify.apps.core.utils.generate_id(),
                profile_id=entity.profile_id,
                name=contact.name,
                email=contact.email,
                phone=contact.phone or "",
                order=contact.order,
            )

        # If entity is ONLY an author (not manufacturer or supplier), delete it
        if not entity.is_manufacturer and not entity.is_supplier:
            # Delete associated contacts first
            ContactProfileContact.objects.filter(entity=entity).delete()
            entity.delete()


def migrate_authors_backward(apps, schema_editor):
    """Reverse migration: Convert AuthorContact back to entity structure."""
    ContactProfile = apps.get_model('teams', 'ContactProfile')
    ContactEntity = apps.get_model('teams', 'ContactEntity')
    ContactProfileContact = apps.get_model('teams', 'ContactProfileContact')
    AuthorContact = apps.get_model('teams', 'AuthorContact')

    # Group author contacts by profile
    for profile in ContactProfile.objects.all():
        authors = AuthorContact.objects.filter(profile=profile)
        if not authors.exists():
            continue

        # Check if profile already has an entity we can mark as author
        existing_entity = ContactEntity.objects.filter(profile=profile).first()
        
        if existing_entity:
            # Mark existing entity as author and add contacts
            existing_entity.is_author = True
            existing_entity.save()
            target_entity = existing_entity
        else:
            # Create a new entity for authors
            first_author = authors.first()
            target_entity = ContactEntity.objects.create(
                id=sbomify.apps.core.utils.generate_id(),
                profile=profile,
                name=f"{profile.name} Authors",
                email=first_author.email if first_author else "no-reply@sbomify.com",
                is_author=True,
                is_manufacturer=False,
                is_supplier=False,
            )

        # Move author contacts to entity contacts
        for author in authors:
            ContactProfileContact.objects.create(
                id=sbomify.apps.core.utils.generate_id(),
                entity=target_entity,
                name=author.name,
                email=author.email,
                phone=author.phone or "",
                order=author.order,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0020_contact_profile_3level_hierarchy'),
    ]

    operations = [
        # Step 1: Create AuthorContact table
        migrations.CreateModel(
            name='AuthorContact',
            fields=[
                ('id', models.CharField(default=sbomify.apps.core.utils.generate_id, max_length=20, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255)),
                ('email', models.EmailField(max_length=254)),
                ('phone', models.CharField(blank=True, max_length=50, null=True)),
                ('order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='authors', to='teams.contactprofile')),
            ],
            options={
                'db_table': 'teams_author_contacts',
                'ordering': ['order', 'name'],
                'unique_together': {('profile', 'name', 'email')},
            },
        ),

        # Step 2: Migrate author data
        migrations.RunPython(migrate_authors_forward, migrate_authors_backward),
    ]

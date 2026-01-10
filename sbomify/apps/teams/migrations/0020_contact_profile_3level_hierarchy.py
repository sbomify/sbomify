# Generated manually for Contact Profile 3-Level Hierarchy migration

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import sbomify.apps.core.utils


def migrate_data_forward(apps, schema_editor):
    """Migrate data from ContactProfile to ContactEntity structure.

    Note: This migration has N+1 queries which is acceptable for one-time migrations.
    Django historical models (via apps.get_model) have limited prefetch_related support.
    For large datasets, consider running during low-traffic periods.
    """
    ContactProfile = apps.get_model('teams', 'ContactProfile')
    ContactEntity = apps.get_model('teams', 'ContactEntity')
    ContactProfileContact = apps.get_model('teams', 'ContactProfileContact')
    Member = apps.get_model('teams', 'Member')

    for profile in ContactProfile.objects.all():
        fallback_email = 'no-reply@sbomify.com'
        try:
            owner = Member.objects.filter(team_id=profile.team_id, role='owner').first()
            if owner:
                User = apps.get_model(settings.AUTH_USER_MODEL.split('.')[0], settings.AUTH_USER_MODEL.split('.')[1])
                user = User.objects.filter(id=owner.user_id).first()
                if user and user.email:
                    fallback_email = user.email
        except Exception:  # nosec B110 - intentionally ignore owner lookup errors and use static default email
            pass

        entity_name = profile.company or profile.supplier_name or profile.vendor or profile.name

        entity = ContactEntity.objects.create(
            id=sbomify.apps.core.utils.generate_id(),
            profile_id=profile.id,
            name=entity_name,
            email=profile.email or fallback_email,
            phone=profile.phone or "",
            address=profile.address or "",
            website_urls=profile.website_urls or [],
            is_manufacturer=True,
            is_supplier=True,
            is_author=True,
        )

        for contact in ContactProfileContact.objects.filter(profile_id=profile.id):
            contact.entity = entity
            if not contact.email:
                contact.email = fallback_email
            contact.save()


def migrate_data_backward(apps, schema_editor):
    """Reverse migration: Move entity data back to profile.

    WARNING: If a profile has multiple entities, only the first entity's data is restored.
    Data from additional entities will be LOST. This is acceptable for rollback purposes
    as the original schema only supported one set of these fields per profile.
    Consider backing up data before running reverse migration on production.
    """
    ContactEntity = apps.get_model('teams', 'ContactEntity')
    ContactProfileContact = apps.get_model('teams', 'ContactProfileContact')

    for entity in ContactEntity.objects.all():
        profile = entity.profile
        # Restore profile fields from first entity
        profile.company = entity.name
        profile.supplier_name = entity.name
        profile.vendor = entity.name
        profile.email = entity.email
        profile.phone = entity.phone
        profile.address = entity.address
        profile.website_urls = entity.website_urls
        profile.save()

        # Update contacts to link back to profile
        for contact in ContactProfileContact.objects.filter(entity=entity):
            contact.profile = profile
            contact.save()


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0019_alter_team_billing_plan_alter_team_is_public_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Step 1: Create ContactEntity table
        migrations.CreateModel(
            name='ContactEntity',
            fields=[
                ('id', models.CharField(default=sbomify.apps.core.utils.generate_id, max_length=20, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255)),
                ('email', models.EmailField(max_length=254)),
                ('phone', models.CharField(blank=True, max_length=50)),
                ('address', models.TextField(blank=True)),
                ('website_urls', models.JSONField(blank=True, default=list)),
                ('is_manufacturer', models.BooleanField(default=False)),
                ('is_supplier', models.BooleanField(default=False)),
                ('is_author', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='entities', to='teams.contactprofile')),
            ],
            options={
                'db_table': 'teams_contact_entities',
                'ordering': ['name'],
                'unique_together': {('profile', 'name')},
            },
        ),

        # Step 2: Add nullable entity FK to ContactProfileContact
        migrations.AddField(
            model_name='contactprofilecontact',
            name='entity',
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.CASCADE, related_name='entity_contacts', to='teams.contactentity'),
        ),

        # Step 3: Data migration
        migrations.RunPython(migrate_data_forward, migrate_data_backward),

        # Step 4: Make email required on ContactProfileContact
        migrations.AlterField(
            model_name='contactprofilecontact',
            name='email',
            field=models.EmailField(max_length=254),
        ),

        # Step 5: Make entity FK non-nullable and update related_name
        migrations.AlterField(
            model_name='contactprofilecontact',
            name='entity',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='contacts', to='teams.contactentity'),
        ),

        # Step 6: Remove old unique_together constraint
        migrations.AlterUniqueTogether(
            name='contactprofilecontact',
            unique_together=set(),
        ),

        # Step 7: Add new unique_together constraint with entity
        migrations.AlterUniqueTogether(
            name='contactprofilecontact',
            unique_together={('entity', 'name', 'email')},
        ),

        # Step 8: Remove profile FK from ContactProfileContact
        migrations.RemoveField(
            model_name='contactprofilecontact',
            name='profile',
        ),

        # Step 9: Remove legacy fields from ContactProfile
        migrations.RemoveField(
            model_name='contactprofile',
            name='company',
        ),
        migrations.RemoveField(
            model_name='contactprofile',
            name='supplier_name',
        ),
        migrations.RemoveField(
            model_name='contactprofile',
            name='vendor',
        ),
        migrations.RemoveField(
            model_name='contactprofile',
            name='email',
        ),
        migrations.RemoveField(
            model_name='contactprofile',
            name='phone',
        ),
        migrations.RemoveField(
            model_name='contactprofile',
            name='address',
        ),
        migrations.RemoveField(
            model_name='contactprofile',
            name='website_urls',
        ),
    ]

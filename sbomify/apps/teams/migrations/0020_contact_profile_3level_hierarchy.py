# Generated manually for Contact Profile 3-Level Hierarchy migration

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import sbomify.apps.core.utils


def migrate_data_forward(apps, schema_editor):
    """Migrate data from ContactProfile to ContactEntity structure."""
    ContactProfile = apps.get_model('teams', 'ContactProfile')
    ContactEntity = apps.get_model('teams', 'ContactEntity')
    ContactProfileContact = apps.get_model('teams', 'ContactProfileContact')
    Member = apps.get_model('teams', 'Member')
    
    # Check if legacy columns exist in the database (handling broken dev envs)
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM teams_contact_profiles LIMIT 0")
        columns = [col[0] for col in cursor.description]
    
    has_legacy_cols = 'company' in columns

    # Use raw query if legacy columns are missing to avoid Django ORM errors
    # or just iterate normally if they are present.
    # Actually, simplest is to just use values() for safe fields if columns missing
    # But values() might not be enough if we need to migrate contacts.
    
    # If columns are missing, we can't use the ORM model safely for those fields.
    # We will iterate safely.
    
    profiles = ContactProfile.objects.all()
    if not has_legacy_cols:
        # If model expects columns but DB doesn't have them, `all()` crashes.
        # So we must use `values()` to restrict selection to existing columns.
        # We need id, team_id, name, is_default for the basic entity creation
        profiles = list(ContactProfile.objects.values('id', 'name', 'team_id', 'is_default', 'email'))
        # Note: 'email' was removed too? Let's check from strict list.
        safe_fields = ['id', 'name', 'team_id', 'is_default']
        if 'email' in columns:
            safe_fields.append('email')
        profiles = ContactProfile.objects.values(*safe_fields)

    for profile_data in profiles:
        # profile_data might be a dict (if values used) or object
        is_object = not isinstance(profile_data, dict)
        
        p_id = profile_data.id if is_object else profile_data['id']
        p_name = profile_data.name if is_object else profile_data['name']
        p_team_id = profile_data.team_id if is_object else profile_data['team_id']
        p_email = (profile_data.email if is_object else profile_data.get('email')) if (is_object or 'email' in safe_fields) else None
        
        # Get legacy fields safely
        company = getattr(profile_data, 'company', None) if is_object and has_legacy_cols else None
        supplier_name = getattr(profile_data, 'supplier_name', None) if is_object and has_legacy_cols else None
        vendor = getattr(profile_data, 'vendor', None) if is_object and has_legacy_cols else None
        phone = getattr(profile_data, 'phone', None) if is_object and has_legacy_cols else None
        address = getattr(profile_data, 'address', None) if is_object and has_legacy_cols else None
        website_urls = getattr(profile_data, 'website_urls', []) if is_object and has_legacy_cols else []

        # Get team owner email for fallback
        # Use simple query to avoid complex ORM issues during migration
        fallback_email = 'no-reply@sbomify.com'
        try:
            owner = Member.objects.filter(team_id=p_team_id, role='owner').first()
            if owner:
                User = apps.get_model(settings.AUTH_USER_MODEL.split('.')[0], settings.AUTH_USER_MODEL.split('.')[1])
                user = User.objects.filter(id=owner.user_id).first()
                if user and user.email:
                    fallback_email = user.email
        except Exception:  # nosec B110 - fallback email is acceptable default
            pass

        # Determine entity name
        entity_name = company or supplier_name or vendor or p_name

        # Create entity
        entity = ContactEntity.objects.create(
            id=sbomify.apps.core.utils.generate_id(),
            profile_id=p_id,
            name=entity_name,
            email=p_email or fallback_email,
            phone=phone or "",
            address=address or "",
            website_urls=website_urls or [],
            is_manufacturer=True,
            is_supplier=True,
            is_author=True,
        )

        # Update contacts
        # ContactProfileContact might have FK to profile.
        # If we used values() for profiles, we need to query contacts manually filtering by p_id
        contacts = ContactProfileContact.objects.filter(profile_id=p_id)
        for contact in contacts:
            contact.entity = entity
            if not contact.email:
                contact.email = fallback_email
            contact.save()


def migrate_data_backward(apps, schema_editor):
    """Reverse migration: Move entity data back to profile."""
    ContactProfile = apps.get_model('teams', 'ContactProfile')
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
        # Step 0: Cleanup for development environment recovery
        # (Handles case where migration failed halfway or a conflicting migration created the table)
        migrations.RunSQL("DROP TABLE IF EXISTS teams_contact_entities CASCADE;"),
        migrations.RunSQL("ALTER TABLE teams_contact_profile_contacts DROP COLUMN IF EXISTS entity_id CASCADE;"),

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

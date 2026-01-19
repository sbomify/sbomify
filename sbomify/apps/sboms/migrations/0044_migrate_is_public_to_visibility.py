# Generated manually for gated documents feature

from django.db import migrations


def migrate_is_public_to_visibility(apps, schema_editor):
    """Migrate is_public boolean to visibility enum."""
    Component = apps.get_model("sboms", "Component")
    
    # Handle NULL is_public (default to private for safety)
    Component.objects.filter(is_public__isnull=True).update(visibility="private")
    
    # Migrate True -> public, False -> private
    Component.objects.filter(is_public=True).update(visibility="public")
    Component.objects.filter(is_public=False).update(visibility="private")
    
    # Validate migration completed successfully
    total = Component.objects.count()
    migrated = Component.objects.exclude(visibility__isnull=True).count()
    if total != migrated:
        raise ValueError(
            f"Migration incomplete: {total} total components, {migrated} migrated. "
            f"{total - migrated} components have NULL visibility."
        )


def reverse_migrate_visibility_to_is_public(apps, schema_editor):
    """Reverse migration: set is_public based on visibility."""
    Component = apps.get_model("sboms", "Component")
    
    # Map visibility back to is_public
    # Note: gated components become False (private) - this is information loss but necessary for reverse
    Component.objects.filter(visibility="public").update(is_public=True)
    Component.objects.filter(visibility__in=("private", "gated")).update(is_public=False)
    
    # Handle NULL visibility (shouldn't happen, but be safe)
    Component.objects.filter(visibility__isnull=True).update(is_public=False)


class Migration(migrations.Migration):

    dependencies = [
        ("sboms", "0043_add_component_visibility_gating"),
    ]

    operations = [
        migrations.RunPython(migrate_is_public_to_visibility, reverse_migrate_visibility_to_is_public),
    ]

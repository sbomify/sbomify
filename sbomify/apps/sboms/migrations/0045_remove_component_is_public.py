# Generated manually to remove legacy is_public field from Component
# 
# This migration removes the is_public field after migration 0044 has migrated
# all data from is_public to visibility. The Component model's save() method
# provides backwards compatibility by syncing is_public <-> visibility until
# this migration runs.

from django.db import migrations


def ensure_visibility_synced(apps, schema_editor):
    """Ensure all components (SBOM and Document) have visibility set correctly before removing is_public."""
    Component = apps.get_model("sboms", "Component")
    
    # Double-check: ensure any components with NULL visibility get a default
    # This applies to both SBOM and Document component types
    Component.objects.filter(visibility__isnull=True).update(visibility="private")
    
    # Ensure visibility matches is_public for any edge cases
    # This applies to both SBOM and Document component types
    Component.objects.filter(is_public=True, visibility__in=("private", "gated")).update(visibility="public")
    Component.objects.filter(is_public=False, visibility="public").update(visibility="private")
    
    # Final validation: ensure all components (both types) have valid visibility
    invalid_visibility_count = Component.objects.exclude(visibility__in=("public", "private", "gated")).count()
    if invalid_visibility_count > 0:
        raise ValueError(
            f"Found {invalid_visibility_count} components with invalid visibility values before removing is_public field"
        )


def reverse_ensure_visibility_synced(apps, schema_editor):
    """Reverse: sync is_public from visibility (for rollback)."""
    Component = apps.get_model("sboms", "Component")
    
    # Map visibility back to is_public
    Component.objects.filter(visibility="public").update(is_public=True)
    Component.objects.filter(visibility__in=("private", "gated")).update(is_public=False)


class Migration(migrations.Migration):

    dependencies = [
        ("sboms", "0044_migrate_is_public_to_visibility"),
    ]

    operations = [
        # Ensure all data is properly migrated before removing field
        migrations.RunPython(ensure_visibility_synced, reverse_ensure_visibility_synced),
        # Remove indexes that reference is_public
        migrations.RemoveIndex(
            model_name="component",
            name="sboms_compo_is_publ_ccec78_idx",
        ),
        migrations.RemoveIndex(
            model_name="component",
            name="sboms_compo_team_id_76162f_idx",
        ),
        # Remove the is_public field
        migrations.RemoveField(
            model_name="component",
            name="is_public",
        ),
    ]

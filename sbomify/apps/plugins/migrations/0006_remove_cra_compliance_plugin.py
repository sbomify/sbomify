"""Remove 'cra-compliance-2024' plugin record.

The plugin was registered in the database but the module
(sbomify.apps.plugins.builtins.cra) was never created, causing
import errors at runtime.
"""

from django.db import migrations
from django.db.models import Q
from django.utils import timezone


def remove_cra_plugin(apps, schema_editor):
    RegisteredPlugin = apps.get_model("plugins", "RegisteredPlugin")
    TeamPluginSettings = apps.get_model("plugins", "TeamPluginSettings")

    plugin_name = "cra-compliance-2024"

    RegisteredPlugin.objects.filter(name=plugin_name).delete()

    if schema_editor.connection.vendor == "postgresql":
        affected_qs = TeamPluginSettings.objects.filter(
            Q(enabled_plugins__contains=[plugin_name]) | Q(plugin_configs__has_key=plugin_name)
        )
    else:
        affected_qs = TeamPluginSettings.objects.all()

    for settings in affected_qs.iterator(chunk_size=1000):
        updates = {}

        if isinstance(settings.enabled_plugins, list) and plugin_name in settings.enabled_plugins:
            updates["enabled_plugins"] = [p for p in settings.enabled_plugins if p != plugin_name]

        if isinstance(settings.plugin_configs, dict) and plugin_name in settings.plugin_configs:
            new_configs = settings.plugin_configs.copy()
            new_configs.pop(plugin_name, None)
            updates["plugin_configs"] = new_configs

        if updates:
            updates["updated_at"] = timezone.now()
            TeamPluginSettings.objects.filter(pk=settings.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [("plugins", "0005_add_config_schema")]
    operations = [migrations.RunPython(remove_cra_plugin, migrations.RunPython.noop)]

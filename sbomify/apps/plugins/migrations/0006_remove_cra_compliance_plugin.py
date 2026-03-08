"""Remove 'cra-compliance-2024' plugin record.

The plugin was registered in the database but the module
(sbomify.apps.plugins.builtins.cra) was never created, causing
import errors at runtime.
"""

from django.db import migrations
from django.db.models import Q


def remove_cra_plugin(apps, schema_editor):
    RegisteredPlugin = apps.get_model("plugins", "RegisteredPlugin")
    TeamPluginSettings = apps.get_model("plugins", "TeamPluginSettings")

    plugin_name = "cra-compliance-2024"

    RegisteredPlugin.objects.filter(name=plugin_name).delete()

    affected = TeamPluginSettings.objects.filter(
        Q(enabled_plugins__contains=[plugin_name]) | Q(plugin_configs__has_key=plugin_name)
    )

    for settings in affected.iterator(chunk_size=1000):
        changed_fields = []

        if isinstance(settings.enabled_plugins, list) and plugin_name in settings.enabled_plugins:
            settings.enabled_plugins = [p for p in settings.enabled_plugins if p != plugin_name]
            changed_fields.append("enabled_plugins")

        if isinstance(settings.plugin_configs, dict) and plugin_name in settings.plugin_configs:
            new_configs = settings.plugin_configs.copy()
            new_configs.pop(plugin_name, None)
            settings.plugin_configs = new_configs
            changed_fields.append("plugin_configs")

        if changed_fields:
            settings.save(update_fields=changed_fields)


class Migration(migrations.Migration):
    dependencies = [("plugins", "0005_add_config_schema")]
    operations = [migrations.RunPython(remove_cra_plugin, migrations.RunPython.noop)]

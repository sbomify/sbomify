"""Remove 'cra-compliance-2024' plugin record.

The plugin was registered in the database but the module
(sbomify.apps.plugins.builtins.cra) was never created, causing
import errors at runtime.
"""

from django.db import migrations


def remove_cra_plugin(apps, schema_editor):
    RegisteredPlugin = apps.get_model("plugins", "RegisteredPlugin")
    TeamPluginSettings = apps.get_model("plugins", "TeamPluginSettings")

    plugin_name = "cra-compliance-2024"

    RegisteredPlugin.objects.filter(name=plugin_name).delete()

    for settings in TeamPluginSettings.objects.all():
        changed = False

        enabled = getattr(settings, "enabled_plugins", None)
        if isinstance(enabled, list) and plugin_name in enabled:
            settings.enabled_plugins = [p for p in enabled if p != plugin_name]
            changed = True

        configs = getattr(settings, "plugin_configs", None)
        if isinstance(configs, dict) and plugin_name in configs:
            new_configs = configs.copy()
            new_configs.pop(plugin_name, None)
            settings.plugin_configs = new_configs
            changed = True

        if changed:
            settings.save()


class Migration(migrations.Migration):
    dependencies = [("plugins", "0005_add_config_schema")]
    operations = [migrations.RunPython(remove_cra_plugin, migrations.RunPython.noop)]

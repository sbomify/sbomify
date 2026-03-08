"""Remove 'cra-compliance-2024' plugin record.

The plugin was registered in the database but the module
(sbomify.apps.plugins.builtins.cra) was never created, causing
import errors at runtime.
"""

from django.db import migrations


def remove_cra_plugin(apps, schema_editor):
    RegisteredPlugin = apps.get_model("plugins", "RegisteredPlugin")
    RegisteredPlugin.objects.filter(name="cra-compliance-2024").delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("plugins", "0005_add_config_schema")]
    operations = [migrations.RunPython(remove_cra_plugin, noop)]

"""Drop ``cra-compliance-2024`` from every workspace's plugin settings.

0006 deleted the ``RegisteredPlugin`` row but left the name in
``TeamPluginSettings.enabled_plugins``, so every upload for those workspaces
asks for a plugin that no longer exists.
"""

from itertools import batched

from django.db import migrations
from django.db.models import Q
from django.utils import timezone

REMOVED_PLUGIN = "cra-compliance-2024"


def drop_removed_plugin(apps, schema_editor):
    TeamPluginSettings = apps.get_model("plugins", "TeamPluginSettings")
    candidates = TeamPluginSettings.objects.filter(
        Q(enabled_plugins__contains=[REMOVED_PLUGIN]) | Q(plugin_configs__has_key=REMOVED_PLUGIN)
    )
    now = timezone.now()
    for batch in batched(candidates.iterator(chunk_size=1000), 1000):
        for settings in batch:
            settings.enabled_plugins = [name for name in settings.enabled_plugins or [] if name != REMOVED_PLUGIN]
            settings.plugin_configs = {k: v for k, v in (settings.plugin_configs or {}).items() if k != REMOVED_PLUGIN}
            settings.updated_at = now
        TeamPluginSettings.objects.bulk_update(batch, ["enabled_plugins", "plugin_configs", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("plugins", "0018_alter_teampluginsettings_options_and_more")]
    operations = [migrations.RunPython(drop_removed_plugin, migrations.RunPython.noop)]

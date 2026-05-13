"""Remove ``github-attestation`` and migrate teams + history to ``sbom-verification``.

The plugin's behaviour has been folded into the unified
``sbom-verification`` plugin (now in the ``attestation`` category). This
migration:

1. Rewrites every ``TeamPluginSettings.enabled_plugins`` list that
   contained ``"github-attestation"`` to reference ``"sbom-verification"``
   instead, deduplicating to avoid double-enabling teams that already
   had both. This keeps existing customers opted-in to attestation
   verification across the rename — they don't have to re-enable.
2. Moves any ``plugin_configs["github-attestation"]`` entry under the
   new key (only if no ``sbom-verification`` config already exists, so
   we never silently overwrite custom settings).
3. Renames historical ``AssessmentRun`` rows from
   ``plugin_name="github-attestation"`` to ``plugin_name="sbom-verification"``
   (also fixes the embedded ``result.plugin_name`` for consistency).
   The category column was already ``"attestation"`` for these runs, so
   BSI's ``requires_one_of`` continues to match — but failure messages
   now reference the plugin name that operators can actually click in
   the UI to re-run.
4. Drops the obsolete ``RegisteredPlugin`` row so the orchestrator no
   longer surfaces it in the UI.

Historical evidence (run timestamps, finding details) is preserved
unchanged — only the ``plugin_name`` label is updated. ADR-004 keeps
the assessment trail in place.
"""

from django.db import migrations

OLD_NAME = "github-attestation"
NEW_NAME = "sbom-verification"


_BULK_BATCH_SIZE = 1000


def migrate_team_plugin_settings(apps, schema_editor):
    """Rewrite ``enabled_plugins`` and ``plugin_configs`` JSON columns.

    Both fields are JSON whose shape varies per row, so a single
    ``UPDATE`` cannot do the work. We stream the candidate rows with
    ``.iterator()`` and ``bulk_update`` only the rows that actually
    needed a change, in batches of ``_BULK_BATCH_SIZE``.

    Filtering on ``contains`` (Postgres ``@>``) trims the candidate set
    to rows that mention the old name in either field, so installs that
    never enabled ``github-attestation`` skip the loop entirely.
    """
    from django.db.models import Q

    TeamPluginSettings = apps.get_model("plugins", "TeamPluginSettings")

    candidates_qs = TeamPluginSettings.objects.filter(
        Q(enabled_plugins__contains=[OLD_NAME]) | Q(plugin_configs__has_key=OLD_NAME)
    )

    pending: list = []
    for settings in candidates_qs.iterator(chunk_size=_BULK_BATCH_SIZE):
        changed = False

        enabled = list(settings.enabled_plugins or [])
        if OLD_NAME in enabled:
            enabled = [name for name in enabled if name != OLD_NAME]
            if NEW_NAME not in enabled:
                enabled.append(NEW_NAME)
            settings.enabled_plugins = enabled
            changed = True

        configs = dict(settings.plugin_configs or {})
        if OLD_NAME in configs:
            old_config = configs.pop(OLD_NAME)
            # Don't clobber a pre-existing custom config for the new
            # plugin — that would be a silent regression in user state.
            configs.setdefault(NEW_NAME, old_config)
            settings.plugin_configs = configs
            changed = True

        if changed:
            pending.append(settings)
            if len(pending) >= _BULK_BATCH_SIZE:
                TeamPluginSettings.objects.bulk_update(pending, ["enabled_plugins", "plugin_configs", "updated_at"])
                pending.clear()

    if pending:
        TeamPluginSettings.objects.bulk_update(pending, ["enabled_plugins", "plugin_configs", "updated_at"])


def rename_historical_assessment_runs(apps, schema_editor):
    """Re-label old ``github-attestation`` runs as ``sbom-verification``.

    The category column is already ``"attestation"`` (the old plugin
    was registered under that category), so the orchestrator's
    ``_check_one_of`` query keeps matching. Renaming the
    ``plugin_name`` column ensures BSI's ``failed_plugins``/``passing_plugins``
    lists reference the plugin name that still exists in the UI, so
    operators see actionable failure messages.

    The plugin_name column rename is a single set-based ``UPDATE`` (no
    Python loop). The embedded ``result["plugin_name"]`` JSON value is
    only present on a subset of rows and needs per-row JSON
    manipulation, so it's handled in a streamed ``bulk_update`` over
    just the rows that need it.

    NOTE on ``v1.x`` runs that were filed under ``category="compliance"``:
    those are intentionally NOT migrated to ``"attestation"``. They
    don't have the ``verification:attestation`` summary finding (added
    in v2.0.0) so flipping their category would falsely satisfy BSI's
    requires_one_of gate on a digest-only "pass". Operators get correct
    attestation evaluation by re-running the unified plugin under v2.0.0.
    """
    AssessmentRun = apps.get_model("plugins", "AssessmentRun")

    runs_with_result_updates: list = []
    runs_qs = AssessmentRun.objects.filter(plugin_name=OLD_NAME)

    for run in runs_qs.only("id", "result").iterator(chunk_size=_BULK_BATCH_SIZE):
        if isinstance(run.result, dict) and run.result.get("plugin_name") == OLD_NAME:
            updated_result = dict(run.result)
            updated_result["plugin_name"] = NEW_NAME
            run.result = updated_result
            runs_with_result_updates.append(run)
            if len(runs_with_result_updates) >= _BULK_BATCH_SIZE:
                AssessmentRun.objects.bulk_update(runs_with_result_updates, ["result"], batch_size=_BULK_BATCH_SIZE)
                runs_with_result_updates.clear()

    if runs_with_result_updates:
        AssessmentRun.objects.bulk_update(runs_with_result_updates, ["result"], batch_size=_BULK_BATCH_SIZE)

    # Set-based rename of the plugin_name column. Runs with already-merged
    # ``result["plugin_name"]`` from the bulk_update above keep their
    # updated JSON, and the column rename applies to all matching rows
    # in one round trip.
    runs_qs.update(plugin_name=NEW_NAME)


def remove_github_attestation_plugin(apps, schema_editor):
    RegisteredPlugin = apps.get_model("plugins", "RegisteredPlugin")
    RegisteredPlugin.objects.filter(name=OLD_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [("plugins", "0012_remove_assessment_run_release_fk")]
    operations = [
        migrations.RunPython(migrate_team_plugin_settings, migrations.RunPython.noop),
        migrations.RunPython(rename_historical_assessment_runs, migrations.RunPython.noop),
        migrations.RunPython(remove_github_attestation_plugin, migrations.RunPython.noop),
    ]

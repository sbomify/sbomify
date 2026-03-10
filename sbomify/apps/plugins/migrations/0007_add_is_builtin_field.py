from django.db import migrations, models


def set_existing_builtins(apps, schema_editor):
    RegisteredPlugin = apps.get_model("plugins", "RegisteredPlugin")
    BUILTIN_NAMES = [
        "ntia-minimum-elements-2021",
        "fda-medical-device-2025",
        "bsi-tr03183-v2.1-compliance",
        "github-attestation",
        "osv",
        "dependency-track",
    ]
    RegisteredPlugin.objects.filter(name__in=BUILTIN_NAMES).update(is_builtin=True)


class Migration(migrations.Migration):
    dependencies = [("plugins", "0006_remove_cra_compliance_plugin")]

    operations = [
        migrations.AddField(
            model_name="registeredplugin",
            name="is_builtin",
            field=models.BooleanField(
                default=False,
                help_text="Builtin plugins are registered by the framework and reconciled on deploy.",
            ),
        ),
        migrations.RunPython(set_existing_builtins, migrations.RunPython.noop),
    ]

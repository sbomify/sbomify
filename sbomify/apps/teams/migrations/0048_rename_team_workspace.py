from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    # Run after every migration that names the model by its old label, or the
    # project state keeps a stale "teams.team" reference.
    dependencies = [
        ("teams", "0047_operator_role"),
        ("vulnerability_scanning", "0013_finding_aliases_db_default"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameModel(old_name="Team", new_name="Workspace"),
        migrations.AlterField(
            model_name="workspace",
            name="members",
            field=models.ManyToManyField(
                related_name="team_set",
                related_query_name="team",
                through="teams.Member",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]

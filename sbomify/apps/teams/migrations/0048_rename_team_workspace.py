from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    # Run after every migration that names the model by its old label, or the
    # project state keeps a stale "teams.team" reference.
    dependencies = [
        ("teams", "0047_operator_role"),
        ("access_tokens", "0011_rename_access_toke_team_id_56c481_idx_access_toke_workspa_298f40_idx_and_more"),
        ("billing", "0007_ensure_existing_teams_comply_with_user_limits"),
        ("compliance", "0018_alter_craassessment_team_and_more"),
        ("controls", "0005_alter_controlcatalog_team"),
        ("documents", "0014_rename_documents_a_team_id_838fe2_idx_documents_a_workspa_17946d_idx_and_more"),
        ("integrations", "0001_initial"),
        ("security_advisories", "0007_initialize_csaf_markers"),
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

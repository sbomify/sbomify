from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("teams", "0022_remove_contactentity_is_author"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="member",
            index=models.Index(fields=["team", "role"], name="teams_member_team_role_idx"),
        ),
    ]

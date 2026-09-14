from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("teams", "0043_team_publish_vulnerability_posture"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="csaf_feed_updated_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text=(
                    "When this workspace's CSAF TLP:WHITE distribution last changed. Bumped whenever a "
                    "public advisory is written or deleted, because a marker aggregated from the advisories "
                    "still present would move backwards when one is removed and a polling aggregator would "
                    "miss the removal."
                ),
                null=True,
            ),
        ),
    ]

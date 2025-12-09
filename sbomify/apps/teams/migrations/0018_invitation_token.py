import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("teams", "0017_team_is_public"),
    ]

    operations = [
        migrations.AddField(
            model_name="invitation",
            name="token",
            field=models.UUIDField(default=uuid.uuid4, unique=True),
        ),
    ]

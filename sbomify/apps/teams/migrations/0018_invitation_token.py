import uuid

from django.db import migrations, models


def gen_uuid(apps, schema_editor):
    Invitation = apps.get_model("teams", "Invitation")
    for row in Invitation.objects.all():
        row.token = uuid.uuid4()
        row.save(update_fields=["token"])


class Migration(migrations.Migration):
    dependencies = [
        ("teams", "0017_team_is_public"),
    ]

    operations = [
        migrations.AddField(
            model_name="invitation",
            name="token",
            field=models.UUIDField(default=uuid.uuid4, null=True),
        ),
        migrations.RunPython(gen_uuid, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name="invitation",
            name="token",
            field=models.UUIDField(default=uuid.uuid4, unique=True),
        ),
    ]

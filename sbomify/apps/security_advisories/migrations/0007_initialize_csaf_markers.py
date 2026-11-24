from django.db import migrations, models
from django.db.models.functions import Coalesce, Greatest, Now


def initialize_markers(apps, schema_editor):
    Team = apps.get_model("teams", "Team")
    Advisory = apps.get_model("security_advisories", "SecurityAdvisory")
    alias = schema_editor.connection.alias
    public = Advisory.objects.using(alias).filter(visibility="public", status__in=("published", "withdrawn"))
    latest = public.filter(team_id=models.OuterRef("pk")).order_by("-updated_at").values("updated_at")[:1]
    Team.objects.using(alias).filter(csaf_feed_updated_at__isnull=True, pk__in=public.values("team_id")).update(
        csaf_feed_updated_at=Greatest(
            Now(), Coalesce(models.Subquery(latest, output_field=models.DateTimeField()), Now())
        )
    )


class Migration(migrations.Migration):
    dependencies = [
        ("security_advisories", "0006_csaf_filename_index"),
        ("teams", "0044_team_csaf_feed_updated_at"),
    ]

    operations = [migrations.RunPython(initialize_markers, migrations.RunPython.noop)]

"""Record when a message was handed to the mailer.

Additive and nullable, so existing rows are untouched and no backfill is
possible or wanted: nothing stamped them, and assuming an old ``PENDING`` row
had been handed over would suppress a send that never happened. They keep the
previous behaviour and the abandonment sweep still reclaims them.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0009_onboardingemail_attempted_address"),
    ]

    operations = [
        migrations.AddField(
            model_name="onboardingemail",
            name="handed_to_mailer_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

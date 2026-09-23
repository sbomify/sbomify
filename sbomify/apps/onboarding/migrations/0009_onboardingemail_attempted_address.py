"""Record which address an ``UNDELIVERABLE`` row refused.

Additive and nullable-by-default (``blank=True`` on a ``CharField`` means an
empty string), so existing rows are untouched and no backfill is possible:
nothing recorded the address at the time, and inferring it from the user's
current one would be a guess that re-sends to whatever refused it.
``OnboardingEmail.suppresses`` honours a blank value as a standing refusal for
exactly that reason.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0008_onboardingemail_undeliverable_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="onboardingemail",
            name="attempted_address",
            field=models.CharField(blank=True, max_length=254),
        ),
    ]

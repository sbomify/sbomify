"""Record which address an ``UNDELIVERABLE`` row refused.

``default=""`` is stated rather than left to Django's implicit empty string
for a ``CharField``. Both emit the same SQL — ``ADD COLUMN … DEFAULT '' NOT
NULL`` followed by ``DROP DEFAULT``, which Postgres 11+ does as metadata only —
but a reader checking whether this is safe to deploy should not have to know
that rule to answer the question.

No backfill, because none is honest: nothing recorded the address at the time,
and inferring it from the user's current one would be a guess that re-sends to
whatever refused it. ``OnboardingEmail.suppresses`` honours a blank value as a
standing refusal for exactly that reason.
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
            field=models.CharField(blank=True, default="", max_length=254),
        ),
    ]

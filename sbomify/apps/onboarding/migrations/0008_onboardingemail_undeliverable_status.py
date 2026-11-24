"""Add the ``undeliverable`` status to ``OnboardingEmail``.

``status`` is a plain ``CharField`` with ``choices``, so Postgres never
constrained its values and no data moves here. The migration exists to keep
Django's model state in step with the field, which is what stops the next
``makemigrations`` from generating this same change again.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0007_onboardingstatus_drip_unsubscribed_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="onboardingemail",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("sent", "Sent"),
                    ("failed", "Failed"),
                    ("undeliverable", "Undeliverable"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]

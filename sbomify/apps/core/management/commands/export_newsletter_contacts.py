"""
Management command to export newsletter subscribers as a Mailjet contact CSV.

Usage: uv run python manage.py export_newsletter_contacts > contacts.csv

The output matches Mailjet's contact list import template
(https://app.mailjet.com/contacts/lists/download_template) so the file can be
uploaded as-is when manually synchronizing the newsletter list.
"""

from __future__ import annotations

from typing import Any

from defusedcsv import csv
from django.core.management.base import BaseCommand

from sbomify.apps.core.models import User
from sbomify.apps.oidc.services import BOT_USERNAME_PREFIX

MAILJET_HEADER = ["Email", "First Name", "Last Name", "Gender", "Birthday", "Interests"]


class Command(BaseCommand):
    help = "Export newsletter subscribers to stdout as a Mailjet contact list CSV."

    def handle(self, *args: Any, **options: Any) -> None:
        subscribers = (
            User.objects.filter(
                newsletter_opt_in=True,
                is_active=True,
                deleted_at__isnull=True,
            )
            .exclude(email="")
            .exclude(username__startswith=BOT_USERNAME_PREFIX)
            .order_by("email")
            .values_list("email", "first_name", "last_name")
        )

        writer = csv.writer(self.stdout)  # type: ignore[no-untyped-call]
        writer.writerow(MAILJET_HEADER)
        for email, first_name, last_name in subscribers:
            writer.writerow([email, first_name, last_name, "", "", ""])

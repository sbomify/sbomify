"""Tests for the export_newsletter_contacts management command."""

from __future__ import annotations

import csv
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from sbomify.apps.core.models import User


def _run_command() -> list[list[str]]:
    out = StringIO()
    call_command("export_newsletter_contacts", stdout=out)
    return list(csv.reader(StringIO(out.getvalue())))


@pytest.mark.django_db
class TestExportNewsletterContacts:
    def test_outputs_mailjet_header_when_no_subscribers(self) -> None:
        rows = _run_command()

        assert rows == [["Email", "First Name", "Last Name", "Gender", "Birthday", "Interests"]]

    def test_exports_subscribed_users_sorted_by_email(self) -> None:
        User.objects.create_user(
            username="zoe", email="zoe@example.org", first_name="Zoe", last_name="Adams", newsletter_opt_in=True
        )
        User.objects.create_user(
            username="amy", email="amy@example.org", first_name="Amy", last_name="Baker", newsletter_opt_in=True
        )

        rows = _run_command()

        assert rows[1:] == [
            ["amy@example.org", "Amy", "Baker", "", "", ""],
            ["zoe@example.org", "Zoe", "Adams", "", "", ""],
        ]

    def test_excludes_opted_out_inactive_deleted_and_emailless_users(self) -> None:
        User.objects.create_user(
            username="in", email="in@example.org", first_name="In", last_name="Cluded", newsletter_opt_in=True
        )
        User.objects.create_user(username="optout", email="optout@example.org", newsletter_opt_in=False)
        User.objects.create_user(username="inactive", email="inactive@example.org", is_active=False)
        User.objects.create_user(username="deleted", email="deleted@example.org", deleted_at=timezone.now())
        User.objects.create_user(username="noemail", email="")
        User.objects.create_user(username="oidc-bot-abc123def456", email="oidc-bot-abc123def456@sbomify.local")

        rows = _run_command()

        assert rows[1:] == [["in@example.org", "In", "Cluded", "", "", ""]]

    def test_quotes_values_containing_commas(self) -> None:
        User.objects.create_user(
            username="von", email="pete@example.org", first_name="Pete", last_name="Von, Burg", newsletter_opt_in=True
        )

        out = StringIO()
        call_command("export_newsletter_contacts", stdout=out)

        assert 'pete@example.org,Pete,"Von, Burg",,,' in out.getvalue()
        rows = list(csv.reader(StringIO(out.getvalue())))
        assert rows[1] == ["pete@example.org", "Pete", "Von, Burg", "", "", ""]

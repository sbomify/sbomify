"""The subject line and the rendered <title> have to say the same thing.

They drifted apart across fifteen templates because nothing tied them
together: the subject lives in the sender, the title in the template, and
neither one fails when the other changes. ``send_test_emails`` already
knows every email and a context that renders it, so this walks the same
list rather than keeping a second one that would drift in its turn.
"""

from __future__ import annotations

import re

import pytest
from django.core import mail
from django.core.management import call_command
from django.test import override_settings

TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)


def _rendered_title(message: mail.EmailMultiAlternatives) -> str | None:
    """Return the collapsed <title> text of the HTML alternative, if there is one."""
    for body, content_type in getattr(message, "alternatives", []) or []:
        if content_type != "text/html":
            continue
        match = TITLE_RE.search(body)
        if match is None:
            return None
        return re.sub(r"\s+", " ", match.group(1)).strip()
    return None


@pytest.fixture
def sent_test_emails() -> list[mail.EmailMultiAlternatives]:
    mail.outbox = []
    with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
        # force: the command refuses to run outside DEBUG, and tests run with
        # DEBUG off. The locmem backend above keeps it from leaving the process.
        call_command("send_test_emails", recipient="qa@example.com", force=True)
    return list(mail.outbox)


@pytest.mark.django_db
def test_every_email_title_matches_its_subject(sent_test_emails) -> None:
    mismatches = [
        (message.subject, _rendered_title(message))
        for message in sent_test_emails
        if _rendered_title(message) != message.subject
    ]
    assert not mismatches, "subject and <title> disagree: " + "; ".join(
        f"{subject!r} vs {title!r}" for subject, title in mismatches
    )


@pytest.mark.django_db
def test_the_command_covers_the_emails_it_claims_to(sent_test_emails) -> None:
    """A drop to zero would make the check above pass while testing nothing."""
    assert len(sent_test_emails) >= 18


@pytest.mark.django_db
def test_no_email_copy_uses_a_dash_as_punctuation(sent_test_emails) -> None:
    """Em and en dashes are a review blocker in user-facing copy."""
    offenders = [message.subject for message in sent_test_emails if set("—–") & set(message.body)]
    assert not offenders, f"dash used as punctuation in: {offenders}"

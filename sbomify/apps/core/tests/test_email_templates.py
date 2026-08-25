"""The subject line and the rendered <title> have to say the same thing.

They drifted apart across twenty templates because nothing tied them
together: the subject lives in the sender, the title in the template, and
neither one fails when the other changes.

Two limits worth knowing before trusting a green run. The subject compared
here is ``send_test_emails``'s own literal, not the sender's, so a sender
that changes its subject alone still passes. And only templates the command
lists are exercised at all, which is what ``test_every_email_template_is_previewable``
is for.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import pytest
from django.core.mail import EmailMessage
from django.core.management import call_command

TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
STYLE_RE = re.compile(r"<style[^>]*>.*?</style>|<!--.*?-->", re.DOTALL | re.IGNORECASE)
DASHES = ("—", "–")

APPS_DIR = Path(__file__).resolve().parents[2]
# base is the layout every email extends; test_template belongs to a billing unit test.
NOT_AN_EMAIL = {"base.html.j2", "test_template.html.j2"}


def _rendered_title(message: EmailMessage) -> str | None:
    """The <title> text, unescaped so it can be compared to a raw subject."""
    html_body = next((body for body, mimetype in message.alternatives if mimetype == "text/html"), None)
    if html_body is None:
        return None
    match = TITLE_RE.search(html_body)
    if match is None:
        return None
    return html.unescape(" ".join(match.group(1).split()))


def _reader_visible_text(message: EmailMessage) -> str:
    """Everything a recipient reads: subject, plain body, and HTML minus its CSS.

    Unescaped at the end, so a dash written as ``&mdash;`` counts the same as
    one written literally.
    """
    parts = [message.subject, message.body]
    parts += [STYLE_RE.sub("", body) for body, mimetype in message.alternatives if mimetype == "text/html"]
    return html.unescape("\n".join(parts))


@pytest.fixture(scope="module")
def sent_test_emails() -> list[EmailMessage]:
    # force: the command refuses to run outside DEBUG, and tests run with DEBUG
    # off. test_settings pins the locmem backend, so nothing leaves the process.
    from django.core import mail

    mail.outbox = []
    call_command("send_test_emails", recipient="qa@example.com", force=True)
    return list(mail.outbox)


def test_every_email_title_matches_its_subject(sent_test_emails: list[EmailMessage]) -> None:
    mismatches = [
        (message.subject, title)
        for message in sent_test_emails
        if (title := _rendered_title(message)) != message.subject
    ]
    assert not mismatches, "subject and <title> disagree: " + "; ".join(
        f"{subject!r} vs {title!r}" for subject, title in mismatches
    )


def test_every_email_template_is_previewable(sent_test_emails: list[EmailMessage]) -> None:
    """A template the command does not list is a template no test can reach."""
    # The template path as Django resolves it, not the bare filename: two apps
    # are free to name a template the same thing, and a set of filenames would
    # collapse them and let one go unlisted unnoticed.
    on_disk = {
        "/".join(path.parts[-3:])
        for path in APPS_DIR.glob("*/templates/*/emails/*.html.j2")
        if path.name not in NOT_AN_EMAIL
    }
    source = (APPS_DIR / "core/management/commands/send_test_emails.py").read_text()
    unlisted = sorted(name for name in on_disk if name not in source)
    assert not unlisted, f"email templates send_test_emails never renders: {unlisted}"


def test_no_email_copy_uses_a_dash_as_punctuation(sent_test_emails: list[EmailMessage]) -> None:
    """Em and en dashes are a review blocker in user-facing copy.

    Subject and both bodies, because a dash in the HTML half is just as
    visible as one in the text half. CSS and comments are stripped first:
    the shared layout uses a dash inside a stylesheet comment.
    """
    offenders = [
        message.subject for message in sent_test_emails if any(dash in _reader_visible_text(message) for dash in DASHES)
    ]
    assert not offenders, f"dash used as punctuation in: {offenders}"


def test_the_mock_workspace_name_still_exercises_escaping(sent_test_emails: list[EmailMessage]) -> None:
    """Without an escapable character the title check passes on data it cannot fail on."""
    from django.core.management import load_command_class

    command: Any = load_command_class("sbomify.apps.core", "send_test_emails")
    assert command is not None
    subjects = " ".join(message.subject for message in sent_test_emails)
    assert "&" in subjects and "'" in subjects, "mock data no longer contains an escapable character"

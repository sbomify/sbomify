"""RFC 9116 security.txt generation service.

Generates a security.txt file from a team's security contact and configuration,
laid out the way BSI TR-03183-3 section 4.2 expects it: the contact lines in
the mandated order (PSIRT mailbox, CSIRT mailbox, report page), a comment line
above each block, and an Expires no more than a year out.
Specs: https://www.rfc-editor.org/rfc/rfc9116 and BSI TR-03183-3.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team

# Max length for URL fields (RFC 9116 recommends fields < 2048 chars)
MAX_FIELD_LENGTH = 2048

# Preferred-Languages constraints (RFC 5646 language tags)
MAX_PREFERRED_LANGUAGES_LENGTH = 200
PREFERRED_LANGUAGES_PATTERN = r"[a-zA-Z0-9, \-]+"

# TR-03183-3 4.2.9: Expires must not be more than a year ahead.
MAX_EXPIRES_AHEAD = timedelta(days=365)


def validate_preferred_languages(value: str) -> str | None:
    """Validate preferred_languages. Returns error message or None if valid."""
    if not value:
        return None
    if len(value) > MAX_PREFERRED_LANGUAGES_LENGTH:
        return f"Preferred languages exceed the maximum length of {MAX_PREFERRED_LANGUAGES_LENGTH} characters"
    if not re.fullmatch(PREFERRED_LANGUAGES_PATTERN, value):
        return "Preferred languages: only letters, digits, commas, spaces, and hyphens allowed"
    return None


def _sanitize_value(value: str) -> str:
    """Strip control characters (newlines, carriage returns, null bytes) to prevent field injection."""
    return re.sub(r"[\r\n\x00]", "", value).strip()


def validate_security_email(value: str) -> str | None:
    """Validate an email for a Contact: mailto line. Returns error message or None if valid."""
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    if not value:
        return None
    if len(value) > MAX_FIELD_LENGTH:
        return f"Email exceeds maximum length of {MAX_FIELD_LENGTH} characters"
    if re.search(r"[\x00-\x1f\x7f\s]", value):
        return "Email contains invalid characters (whitespace or control characters)"
    try:
        validate_email(value)
    except ValidationError:
        return "Enter a valid email address"
    return None


def _get_security_contact_email(team: Team, config: dict[str, Any]) -> str | None:
    """Find the security contact email.

    If a specific contact_id is set in config, use that contact.
    Falls back to the security contact on the default profile if the
    configured contact no longer exists.
    """
    from sbomify.apps.teams.models import ContactProfileContact

    contact_id = config.get("contact_id", "")
    if contact_id:
        email = (
            ContactProfileContact.objects.filter(
                id=contact_id,
                entity__profile__team=team,
                entity__profile__is_component_private=False,
            )
            .values_list("email", flat=True)
            .first()
        )
        if email:
            return email
        # Configured contact no longer exists — fall through to default

    return (
        ContactProfileContact.objects.filter(
            entity__profile__team=team,
            entity__profile__is_default=True,
            entity__profile__is_component_private=False,
            is_security_contact=True,
        )
        .values_list("email", flat=True)
        .first()
    )


def validate_security_txt_url(url: str) -> str | None:
    """Validate a URL for security.txt. Returns error message or None if valid."""
    from urllib.parse import urlparse

    if not url:
        return None
    if len(url) > MAX_FIELD_LENGTH:
        return f"URL exceeds maximum length of {MAX_FIELD_LENGTH} characters"
    if re.search(r"[\x00-\x1f\x7f\s]", url):
        return "URL contains invalid characters (whitespace or control characters)"
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        return "URL must use https:// or http:// scheme"
    if not parsed.netloc:
        return "URL must include a hostname"
    return None


def clean_expires(raw: str) -> str:
    """A valid Expires value: in the future, at most a year out, whole seconds.

    Falls back to a year from now when the stored value is missing, past,
    unparseable, or further out than TR-03183-3 4.2.9 allows.
    """
    now = datetime.now(timezone.utc)
    cap = now + MAX_EXPIRES_AHEAD
    try:
        expires_dt = datetime.fromisoformat(raw) if raw else None
        if expires_dt and expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        expires_dt = None
    if not expires_dt or expires_dt <= now or expires_dt > cap:
        expires_dt = cap
    return expires_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_url(config: dict[str, Any], key: str) -> str:
    raw = str(config.get(key, "")).strip()
    if raw and validate_security_txt_url(raw) is None:
        return _sanitize_value(raw)
    return ""


def generate_security_txt(team: Team) -> str:
    """Generate RFC 9116 / TR-03183-3 security.txt content for a team.

    Returns empty string if security.txt is disabled or no security contact
    is configured. All values are sanitized to prevent newline/field injection.

    Args:
        team: The Team instance to generate security.txt for.

    Returns:
        The security.txt file content as a string, or empty string.
    """
    config: dict[str, Any] = team.security_txt_config or {}

    if not config.get("enabled", False):
        return ""

    email = _get_security_contact_email(team, config)
    if not email:
        return ""

    lines: list[str] = []

    # TR-03183-3 4.2.3 mandates the contact order: the PSIRT mailbox first,
    # the CSIRT mailbox second, the report page URI third.
    lines.append("# Our security addresses")
    lines.append(f"Contact: mailto:{_sanitize_value(email)}")
    csirt_email = str(config.get("csirt_email", "")).strip()
    if csirt_email and validate_security_email(csirt_email) is None:
        lines.append(f"Contact: mailto:{_sanitize_value(csirt_email)}")
    if report_url := _valid_url(config, "report_url"):
        lines.append(f"Contact: {report_url}")

    # Encryption: multiple URLs supported (RFC 9116 allows repeated Encryption fields)
    encryption_lines: list[str] = []
    if "encryption_urls" in config and isinstance(config["encryption_urls"], list):
        for raw_url in config["encryption_urls"]:
            raw_url = str(raw_url).strip()
            if raw_url and validate_security_txt_url(raw_url) is None:
                value = _sanitize_value(raw_url)
                if value:
                    encryption_lines.append(f"Encryption: {value}")
    # Backward compat: single encryption_url (legacy configs)
    elif encryption_url := str(config.get("encryption_url", "")).strip():
        if validate_security_txt_url(encryption_url) is None:
            encryption_lines.append(f"Encryption: {_sanitize_value(encryption_url)}")
    if encryption_lines:
        lines.append("# Our OpenPGP keys")
        lines.extend(encryption_lines)

    if policy_url := _valid_url(config, "policy_url"):
        lines.append("# Our security policy")
        lines.append(f"Policy: {policy_url}")

    if acknowledgments_url := _valid_url(config, "acknowledgments_url"):
        lines.append("# Our acknowledgments page")
        lines.append(f"Acknowledgments: {acknowledgments_url}")

    # CSAF 2.0 section 7.1.8: points at the provider-metadata.json.
    if csaf_url := _valid_url(config, "csaf_url"):
        lines.append("# Our CSAF provider metadata")
        lines.append(f"CSAF: {csaf_url}")

    if hiring_url := _valid_url(config, "hiring_url"):
        lines.append(f"Hiring: {hiring_url}")

    if canonical_url := _valid_url(config, "canonical_url"):
        lines.append(f"Canonical: {canonical_url}")

    # Optional non-URL fields — reuse centralized validation
    if preferred_languages := _sanitize_value(str(config.get("preferred_languages", ""))):
        if validate_preferred_languages(preferred_languages) is None:
            lines.append(f"Preferred-Languages: {preferred_languages}")

    # Required: Expires — stored value if usable, clamped to a year out either way
    lines.append(f"Expires: {clean_expires(str(config.get('expires', '')))}")

    return "\n".join(lines) + "\n"

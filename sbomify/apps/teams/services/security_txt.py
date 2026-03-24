"""RFC 9116 security.txt generation service.

Generates a security.txt file from a team's security contact and configuration.
Spec: https://www.rfc-editor.org/rfc/rfc9116
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team

# Max length for URL fields (RFC 9116 recommends fields < 2048 chars)
MAX_FIELD_LENGTH = 2048


def _sanitize_value(value: str) -> str:
    """Strip control characters (newlines, carriage returns, null bytes) to prevent field injection."""
    return re.sub(r"[\r\n\x00]", "", value).strip()


def _get_security_contact_email(team: Team, config: dict[str, Any]) -> str | None:
    """Find the security contact email.

    If a specific contact_id is set in config, use that contact.
    Otherwise fall back to the security contact on the default profile.
    """
    from sbomify.apps.teams.models import ContactProfileContact

    contact_id = config.get("contact_id", "")
    if contact_id:
        return (
            ContactProfileContact.objects.filter(
                id=contact_id,
                entity__profile__team=team,
            )
            .values_list("email", flat=True)
            .first()
        )

    return (
        ContactProfileContact.objects.filter(
            entity__profile__team=team,
            entity__profile__is_default=True,
            is_security_contact=True,
        )
        .values_list("email", flat=True)
        .first()
    )


def validate_security_txt_url(url: str) -> str | None:
    """Validate a URL for security.txt. Returns error message or None if valid."""
    if not url:
        return None
    if len(url) > MAX_FIELD_LENGTH:
        return f"URL exceeds maximum length of {MAX_FIELD_LENGTH} characters"
    if not url.startswith(("https://", "http://")):
        return "URL must start with https:// or http://"
    if re.search(r"[\r\n\x00]", url):
        return "URL contains invalid control characters"
    return None


def generate_security_txt(team: Team) -> str:
    """Generate RFC 9116 security.txt content for a team.

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

    # Required: Contact (mailto URI) — sanitize email to prevent injection
    lines.append(f"Contact: mailto:{_sanitize_value(email)}")

    # Optional fields — all sanitized against newline injection
    optional_fields = [
        ("Policy", "policy_url"),
        ("Encryption", "encryption_url"),
        ("Acknowledgments", "acknowledgments_url"),
        ("Canonical", "canonical_url"),
        ("Hiring", "hiring_url"),
        ("Preferred-Languages", "preferred_languages"),
    ]
    for field_name, config_key in optional_fields:
        if value := _sanitize_value(str(config.get(config_key, ""))):
            lines.append(f"{field_name}: {value}")

    # Required: Expires — use stored value if valid and not past, else generate fresh
    expires_str = str(config.get("expires", ""))
    try:
        expires_dt = datetime.fromisoformat(expires_str) if expires_str else None
        if expires_dt and expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        expires_dt = None
    if not expires_dt or expires_dt <= datetime.now(timezone.utc):
        expires_str = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
    lines.append(f"Expires: {_sanitize_value(expires_str)}")

    return "\n".join(lines) + "\n"

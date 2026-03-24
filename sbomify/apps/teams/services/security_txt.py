"""RFC 9116 security.txt generation service.

Generates a security.txt file from a team's security contact and configuration.
Spec: https://www.rfc-editor.org/rfc/rfc9116
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team


def _get_security_contact_email(team: Team) -> str | None:
    """Find the security contact email from the team's default contact profile."""
    from sbomify.apps.teams.models import ContactProfileContact

    return (
        ContactProfileContact.objects.filter(
            entity__profile__team=team,
            entity__profile__is_default=True,
            is_security_contact=True,
        )
        .values_list("email", flat=True)
        .first()
    )


def generate_security_txt(team: Team) -> str:
    """Generate RFC 9116 security.txt content for a team.

    Returns empty string if security.txt is disabled or no security contact
    is configured.

    Args:
        team: The Team instance to generate security.txt for.

    Returns:
        The security.txt file content as a string, or empty string.
    """
    config: dict[str, object] = team.security_txt_config or {}

    if not config.get("enabled", False):
        return ""

    email = _get_security_contact_email(team)
    if not email:
        return ""

    lines: list[str] = []

    # Required: Contact (mailto URI)
    lines.append(f"Contact: mailto:{email}")

    # Optional fields
    if policy_url := config.get("policy_url", ""):
        lines.append(f"Policy: {policy_url}")

    if encryption_url := config.get("encryption_url", ""):
        lines.append(f"Encryption: {encryption_url}")

    if acknowledgments_url := config.get("acknowledgments_url", ""):
        lines.append(f"Acknowledgments: {acknowledgments_url}")

    if canonical_url := config.get("canonical_url", ""):
        lines.append(f"Canonical: {canonical_url}")

    if hiring_url := config.get("hiring_url", ""):
        lines.append(f"Hiring: {hiring_url}")

    if preferred_languages := config.get("preferred_languages", ""):
        lines.append(f"Preferred-Languages: {preferred_languages}")

    # Required: Expires (default: 1 year from now)
    expires = config.get("expires")
    if not expires:
        expires = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
    lines.append(f"Expires: {expires}")

    return "\n".join(lines) + "\n"

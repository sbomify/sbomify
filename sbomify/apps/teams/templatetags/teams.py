import re
from datetime import datetime, timedelta

from django import template
from django.utils import timezone

from sbomify.apps.teams.utils import update_user_teams_session

register = template.Library()

# Shared constants for workspace suffix handling
WORKSPACE_SUFFIX = "'s Workspace"
WORKSPACE_SUFFIX_LOWER = "'s workspace"
# Legacy variants with curly apostrophe
LEGACY_SUFFIXES = (WORKSPACE_SUFFIX_LOWER, "'s workspace")

# Workspace key validation pattern - must match client-side pattern
# Only alphanumeric, underscores, and hyphens allowed
VALID_WORKSPACE_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_workspace_key(key: str) -> bool:
    """
    Validate workspace key format to prevent XSS attacks.

    Args:
        key: Workspace key to validate

    Returns:
        True if key is valid, False otherwise
    """
    if not key or not isinstance(key, str):
        return False
    return bool(VALID_WORKSPACE_KEY_PATTERN.match(key))


def _strip_workspace_suffix(name: str) -> str:
    """Strip workspace suffix from name for processing."""
    normalized = name.lower()
    for suffix in LEGACY_SUFFIXES:
        if normalized.endswith(suffix):
            return name[: -len(suffix)].strip()
    return name


@register.filter
def workspace_display(name: str | None) -> str:
    """Display workspace names with a single `'s Workspace` suffix."""
    if not name:
        return "Workspace"

    trimmed = str(name).strip()
    normalized = trimmed.casefold()
    if any(normalized.endswith(suffix) for suffix in LEGACY_SUFFIXES):
        return trimmed

    return f"{trimmed}{WORKSPACE_SUFFIX}"


@register.filter
def modulo(value, arg):
    """Return value modulo arg."""
    try:
        return int(value) % int(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def avatar_color_index(name: str | None) -> int:
    """
    Return avatar color index (0-4) based on first letter of workspace name.

    Maps A-Z to colors 0-4 for consistent coloring.
    """
    if not name:
        return 0

    name_str = str(name).strip()
    first_char = name_str[0].upper() if name_str else "A"

    if first_char.isalpha():
        return (ord(first_char) - ord("A")) % 5

    return ord(first_char) % 5


@register.filter
def workspace_initials(name: str | None) -> str:
    """
    Generate workspace initials for avatar display.
    - If 1 word: first 2 letters
    - If 2+ words: 1 letter from first + 1 letter from second
    """
    if not name:
        return "WS"

    cleaned_name = _strip_workspace_suffix(str(name).strip())
    words = cleaned_name.split()

    if len(words) == 0:
        return "WS"
    elif len(words) == 1:
        word = words[0]
        return word[:2].upper() if len(word) >= 2 else word.upper()
    else:
        first_word = words[0]
        second_word = words[1]
        first_letter = first_word[0].upper() if first_word else ""
        second_letter = second_word[0].upper() if second_word else ""
        return first_letter + second_letter


@register.simple_tag
def current_member(members):
    if not members:
        return None
    return next((member for member in members if member.is_me), None)


@register.simple_tag(takes_context=True)
def user_workspaces(context):
    request = context.get("request")
    if not request or not hasattr(request, "user") or not request.user.is_authenticated:
        return {}

    user_teams = request.session.get("user_teams")
    last_checked_raw = request.session.get("user_teams_checked_at")
    last_checked = None
    if last_checked_raw:
        try:
            last_checked = datetime.fromisoformat(last_checked_raw)
            if timezone.is_naive(last_checked):
                last_checked = timezone.make_aware(
                    last_checked,
                    timezone.get_current_timezone(),
                )
        except ValueError:
            last_checked = None

    ttl_seconds = 300
    needs_refresh = (
        not user_teams
        or not request.session.get("user_teams_version")
        or not last_checked
        or (timezone.now() - last_checked) > timedelta(seconds=ttl_seconds)
    )

    if needs_refresh:
        user_teams = update_user_teams_session(request, request.user)

    validated_teams = {}
    import logging

    logger = logging.getLogger(__name__)
    for key, team_data in (user_teams or {}).items():
        if _validate_workspace_key(key):
            validated_teams[key] = team_data
        else:
            key_preview = key[:20] if len(key) > 20 else key
            logger.warning(f"Invalid workspace key format detected and filtered: {key_preview}...")

    user_teams = validated_teams

    current_team = request.session.get("current_team") or {}
    current_key = current_team.get("key")

    # Validate current key
    if current_key and not _validate_workspace_key(current_key):
        current_key = None

    if (not current_key or current_key not in user_teams) and user_teams:
        # Find first valid key
        valid_keys = (k for k in user_teams.keys() if _validate_workspace_key(k))
        current_key = next(valid_keys, None)
        if current_key:
            request.session["current_team"] = {
                "key": current_key,
                **user_teams[current_key],
            }
            request.session["current_team_key"] = current_key
            request.session.modified = True
        else:
            current_key = None
    else:
        request.session["current_team_key"] = current_key

    context["current_workspace_key"] = current_key
    return user_teams

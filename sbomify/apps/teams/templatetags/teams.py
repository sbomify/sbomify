import hashlib
import logging
import re
from datetime import datetime, timedelta

from django import template
from django.utils import timezone

from sbomify.apps.teams.utils import update_user_teams_session

register = template.Library()
logger = logging.getLogger(__name__)

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


@register.filter
def user_initials(user) -> str:
    """
    Generate user initials for avatar display using the same logic as workspace_initials.
    - If user has first_name and last_name: first letter of each
    - If user has only first_name: first 2 letters
    - If user has only username: apply workspace_initials logic to username
    - Fallback: "U"
    """
    if not user:
        return "U"

    # Try to get full name
    first_name = getattr(user, "first_name", None) or ""
    last_name = getattr(user, "last_name", None) or ""

    # If we have both first and last name, use first letter of each
    if first_name.strip() and last_name.strip():
        return (first_name[0] + last_name[0]).upper()

    # If we have only first name, use first 2 letters
    if first_name.strip():
        name = first_name.strip()
        return name[:2].upper() if len(name) >= 2 else name.upper()

    # Fall back to username and apply workspace_initials logic
    username = getattr(user, "username", None) or ""
    if username:
        # Extract clean name from email-based usernames
        if "@" in username:
            name = username.split("@")[0]
        elif "." in username:
            name = username.split(".")[0]
        else:
            name = username

        name = name.strip()
        words = name.split()

        if len(words) == 0:
            return "U"
        elif len(words) == 1:
            word = words[0]
            return word[:2].upper() if len(word) >= 2 else word.upper()
        else:
            first_word = words[0]
            second_word = words[1]
            first_letter = first_word[0].upper() if first_word else ""
            second_letter = second_word[0].upper() if second_word else ""
            return first_letter + second_letter

    return "U"


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
    # Check if user's teams were invalidated (e.g., after access request approval)
    # Use both cache (for production) and database check (for DEBUG mode)
    from django.core.cache import cache

    from sbomify.apps.teams.models import Member

    cache_key = f"user_teams_invalidate:{request.user.id}"
    was_invalidated_by_cache = cache.get(cache_key, False)

    # Also check database: if member count changed, we need to refresh
    # This works even when cache is disabled (DEBUG mode)
    current_member_count = Member.objects.filter(user=request.user).count()
    session_member_count = len(user_teams) if user_teams else 0
    member_count_changed = current_member_count != session_member_count

    was_invalidated = was_invalidated_by_cache or member_count_changed

    # If invalidated, clear session data to force refresh
    if was_invalidated:
        request.session.pop("user_teams", None)
        request.session.pop("user_teams_version", None)
        request.session.pop("user_teams_checked_at", None)
        user_teams = None
        last_checked = None
        if was_invalidated_by_cache:
            cache.delete(cache_key)  # Clear the invalidation flag
        request.session.modified = True

    needs_refresh = (
        not user_teams
        or not request.session.get("user_teams_version")
        or not last_checked
        or (timezone.now() - last_checked) > timedelta(seconds=ttl_seconds)
    )

    if needs_refresh:
        user_teams = update_user_teams_session(request, request.user)

    validated_teams = {}
    for key, team_data in (user_teams or {}).items():
        if _validate_workspace_key(key):
            validated_teams[key] = team_data
        else:
            # Log hash instead of actual key to prevent information leakage
            key_hash = hashlib.sha256(key.encode()).hexdigest()[:16]
            logger.warning(
                "Invalid workspace key format detected and filtered: hash=%s",
                key_hash,
            )

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

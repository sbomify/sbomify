"""Template tags and filters for plugins app."""

from django import template

register = template.Library()


@register.filter
def format_run_reason(reason: str) -> str:
    """Format assessment run reason for display."""
    reasons = {
        "on_upload": "Upload",
        "manual": "Manual",
        "scheduled": "Scheduled",
        "config_change": "Config Change",
        "migration": "Migration",
    }
    return reasons.get(reason, reason)

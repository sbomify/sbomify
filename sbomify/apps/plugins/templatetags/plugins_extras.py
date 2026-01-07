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


@register.filter
def status_border_class(status: str) -> str:
    """Map finding status to Bootstrap border CSS class."""
    classes = {
        "pass": "border-success",
        "fail": "border-warning",
        "error": "border-danger",
        "warning": "border-info",
        "info": "border-secondary",
    }
    return classes.get(status, "border-secondary")


@register.filter
def status_text_class(status: str) -> str:
    """Map finding status to Bootstrap text color CSS class."""
    classes = {
        "pass": "text-success",
        "fail": "text-warning",
        "error": "text-danger",
        "warning": "text-info",
        "info": "text-secondary",
    }
    return classes.get(status, "text-secondary")


@register.filter
def status_icon(status: str) -> str:
    """Map finding status to Font Awesome icon class."""
    icons = {
        "pass": "fas fa-check-circle",
        "fail": "fas fa-times-circle",
        "warning": "fas fa-exclamation-circle",
        "error": "fas fa-exclamation-triangle",
        "info": "fas fa-info-circle",
    }
    return icons.get(status, "fas fa-info-circle")

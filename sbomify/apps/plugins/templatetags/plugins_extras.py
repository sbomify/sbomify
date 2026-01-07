"""Template tags and filters for plugins app."""

from django import template

register = template.Library()


@register.filter
def format_run_reason(reason: str) -> str:
    """Format assessment run reason for display.

    Args:
        reason: The run reason code. Expected values:
            - "on_upload": Triggered by SBOM upload
            - "manual": Manually triggered by user
            - "scheduled": Triggered by scheduled job
            - "config_change": Triggered by configuration change
            - "migration": Triggered during data migration

    Returns:
        Human-readable display string for the reason.
    """
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
    """Map finding status to Bootstrap border CSS class.

    Args:
        status: The finding status. Expected values:
            - "pass": Finding passed validation
            - "fail": Finding failed validation
            - "error": Error occurred during validation
            - "warning": Warning condition detected
            - "info": Informational finding

    Returns:
        Bootstrap border class (e.g., "border-success", "border-warning").
    """
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
    """Map finding status to Bootstrap text color CSS class.

    Args:
        status: The finding status. Expected values:
            - "pass": Finding passed validation
            - "fail": Finding failed validation
            - "error": Error occurred during validation
            - "warning": Warning condition detected
            - "info": Informational finding

    Returns:
        Bootstrap text color class (e.g., "text-success", "text-warning").
    """
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
    """Map finding status to Font Awesome icon class.

    Args:
        status: The finding status. Expected values:
            - "pass": Finding passed validation
            - "fail": Finding failed validation
            - "error": Error occurred during validation
            - "warning": Warning condition detected
            - "info": Informational finding

    Returns:
        Font Awesome icon class (e.g., "fas fa-check-circle").
    """
    icons = {
        "pass": "fas fa-check-circle",
        "fail": "fas fa-times-circle",
        "warning": "fas fa-exclamation-circle",
        "error": "fas fa-exclamation-triangle",
        "info": "fas fa-info-circle",
    }
    return icons.get(status, "fas fa-info-circle")

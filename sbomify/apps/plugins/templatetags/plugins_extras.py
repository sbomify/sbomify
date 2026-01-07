"""Template tags and filters for plugins app."""

import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

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


@register.filter
def format_finding_description(description: str) -> str:
    """Format finding description with styled package lists.

    Parses descriptions containing "Missing for:" followed by a list of
    package names/paths and renders them as styled HTML spans for better
    readability. Includes expand/collapse for long lists.

    Args:
        description: The finding description text. May contain patterns like:
            - "Description text. Missing for: pkg1, pkg2, pkg3 and N more"
            - "Description text. Missing for: pkg1, pkg2, pkg3"

    Returns:
        HTML-safe string with package names wrapped in styled spans.
    """
    if not description:
        return ""

    # Pattern to match "Missing for: package1, package2, ... and N more"
    pattern = r"(.*?)(Missing for:|Not found in:|Missing in:)\s*(.+)"
    match = re.match(pattern, description, re.IGNORECASE | re.DOTALL)

    if not match:
        return escape(description)

    prefix_text = match.group(1).strip()
    missing_label = match.group(2)
    packages_text = match.group(3).strip()

    # Split packages by comma
    packages = [p.strip() for p in packages_text.split(",") if p.strip()]

    # Build HTML
    html_parts = []

    if prefix_text:
        html_parts.append(f"<span>{escape(prefix_text)}</span>")

    # Package list container
    pkg_html = [f'<span class="missing-label fw-medium">{escape(missing_label)}</span>']
    pkg_html.append('<span class="missing-packages">')

    # Show first 5 packages initially, rest are hidden but expandable
    visible_count = 5
    hidden_count = max(0, len(packages) - visible_count)

    for i, pkg in enumerate(packages):
        hidden_class = " pkg-hidden" if i >= visible_count else ""
        pkg_html.append(f'<span class="pkg{hidden_class}" title="{escape(pkg)}">{escape(pkg)}</span>')

    # Show toggle if there are hidden items
    if hidden_count > 0:
        pkg_html.append(
            f'<button type="button" class="pkg-toggle" data-expanded="false" '
            f'onclick="togglePackages(this)">'
            f'<span class="pkg-toggle-more">Show all {len(packages)}</span>'
            f'<span class="pkg-toggle-less" style="display:none;">Show less</span>'
            f"</button>"
        )

    pkg_html.append("</span>")
    html_parts.append(" ".join(pkg_html))

    return mark_safe(" ".join(html_parts))

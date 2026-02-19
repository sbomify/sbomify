"""Template tags and filters for plugins app."""

import re

from django import template
from django.utils.html import conditional_escape, format_html, format_html_join

register = template.Library()

# Number of packages to show before collapsing with "Show all" toggle
VISIBLE_PACKAGE_COUNT = 5


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
    classes = {  # nosec B105
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
    classes = {  # nosec B105
        "pass": "text-success",
        "fail": "text-warning",
        "error": "text-danger",
        "warning": "text-info",
        "info": "text-secondary",
    }
    return classes.get(status, "text-secondary")


@register.filter
def severity_border_class(severity: str) -> str:
    """Map vulnerability severity to border CSS class.

    Args:
        severity: The severity level (critical, high, medium, low).

    Returns:
        CSS border class string.
    """
    classes = {
        "critical": "border-danger",
        "high": "border-warning",
        "medium": "border-info",
        "low": "border-success",
    }
    return classes.get(severity, "border-secondary")


@register.filter
def severity_text_class(severity: str) -> str:
    """Map vulnerability severity to text color CSS class.

    Args:
        severity: The severity level (critical, high, medium, low).

    Returns:
        CSS text color class string.
    """
    classes = {
        "critical": "text-danger",
        "high": "text-warning",
        "medium": "text-info",
        "low": "text-success",
    }
    return classes.get(severity, "text-secondary")


@register.filter
def severity_icon(severity: str) -> str:
    """Map vulnerability severity to Font Awesome icon class.

    Args:
        severity: The severity level (critical, high, medium, low).

    Returns:
        Font Awesome icon class string.
    """
    icons = {
        "critical": "fas fa-shield-alt",
        "high": "fas fa-shield-alt",
        "medium": "fas fa-exclamation-circle",
        "low": "fas fa-info-circle",
    }
    return icons.get(severity, "fas fa-info-circle")


@register.filter
def is_security_category(category: str) -> bool:
    """Check if the category is a security category.

    Args:
        category: The assessment category string.

    Returns:
        True if the category is "security".
    """
    return category == "security"


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
    icons = {  # nosec B105
        "pass": "fas fa-check-circle",
        "fail": "fas fa-times-circle",
        "warning": "fas fa-exclamation-circle",
        "error": "fas fa-exclamation-triangle",
        "info": "fas fa-info-circle",
    }
    return icons.get(status, "fas fa-info-circle")


def _build_package_span_args(packages: list[str]) -> list[tuple[str, str, str]]:
    """Build argument tuples for package spans.

    Args:
        packages: List of package names.

    Returns:
        List of (hidden_class, pkg, pkg) tuples for format_html_join.
    """
    args = []
    for i, pkg in enumerate(packages):
        hidden_class = " pkg-hidden" if i >= VISIBLE_PACKAGE_COUNT else ""
        args.append((hidden_class, pkg, pkg))
    return args


@register.filter
def format_finding_description(description: str) -> str:
    """Format finding description with styled package lists.

    Parses descriptions containing "Missing for:" followed by a list of
    package names/paths and renders them as styled HTML spans for better
    readability. Includes expand/collapse for long lists.

    All user input is properly escaped via format_html/format_html_join.

    Args:
        description: The finding description text. May contain patterns like:
            - "Description text. Missing for: pkg1, pkg2, pkg3 and N more"
            - "Description text. Missing for: pkg1, pkg2, pkg3"

    Returns:
        HTML-safe string with package names wrapped in styled spans.
    """
    if not description:
        return ""

    # Guard against excessively large descriptions (>100KB) to prevent regex backtracking
    if len(description) > 100_000:
        return conditional_escape(description)

    # Pattern to match "Missing for: package1, package2, ... and N more"
    pattern = r"(.*?)(Missing for:|Not found in:|Missing in:)\s*(.+)"
    match = re.match(pattern, description, re.IGNORECASE | re.DOTALL)

    if not match:
        return conditional_escape(description)

    prefix_text = match.group(1).strip()
    missing_label = match.group(2)
    packages_text = match.group(3).strip()

    # Split packages by comma
    packages = [p.strip() for p in packages_text.split(",") if p.strip()]

    # Build package spans using format_html_join (properly escapes all args)
    hidden_count = max(0, len(packages) - VISIBLE_PACKAGE_COUNT)
    pkg_span_args = _build_package_span_args(packages)
    pkg_spans_joined = format_html_join(" ", '<span class="pkg{}" title="{}">{}</span>', pkg_span_args)

    # Build the toggle button if needed (static HTML, only integer from len())
    toggle_html = ""
    if hidden_count > 0:
        toggle_html = format_html(
            '<button type="button" class="pkg-toggle" data-expanded="false" '
            'onclick="togglePackages(this)">'
            '<span class="pkg-toggle-more">Show all {}</span>'
            '<span class="pkg-toggle-less" style="display:none;">Show less</span>'
            "</button>",
            len(packages),
        )

    # Build the missing packages section
    packages_html = format_html(
        '<span class="missing-label fw-medium">{}</span> <span class="missing-packages">{} {}</span>',
        missing_label,
        pkg_spans_joined,
        toggle_html,
    )

    # Return with optional prefix
    if prefix_text:
        return format_html("<span>{}</span> {}", prefix_text, packages_html)
    return packages_html


@register.filter
def has_compliance_failures(assessment_runs: dict) -> bool:
    """Check if any compliance-category assessment has failures.

    Used to conditionally show the consulting CTA banner only for
    compliance assessments (NTIA, CISA, CRA, FDA), not for other
    assessment types like security/vulnerabilities or license.

    Args:
        assessment_runs: Dict containing 'latest_runs' list of assessment runs.
            Each run should have 'category', 'status', and optionally 'result'
            with 'summary' containing 'fail_count' and 'error_count'.

    Returns:
        True if any compliance assessment has failures, False otherwise.
    """
    if not assessment_runs:
        return False

    latest_runs = assessment_runs.get("latest_runs", [])
    for run in latest_runs:
        if run.get("category") != "compliance":
            continue
        # Check if the run itself failed (execution error)
        if run.get("status") == "failed":
            return True
        # Check if the run completed but has failing findings
        if run.get("status") == "completed":
            result = run.get("result") or {}
            summary = result.get("summary") or {}
            if summary.get("fail_count", 0) > 0 or summary.get("error_count", 0) > 0:
                return True
    return False

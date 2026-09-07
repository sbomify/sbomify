"""Template tags and filters for plugins app."""

import logging
import re
from typing import Any

from django import template
from django.utils.html import conditional_escape, format_html, format_html_join

logger = logging.getLogger(__name__)

register = template.Library()

# Number of packages to show before collapsing with "Show all" toggle
VISIBLE_PACKAGE_COUNT = 5

# The CommonMark an advisory body arrives in. OSV serves GHSA's `details`
# verbatim, so "### Impact", backticked package names and reference links all
# reach us as markup. Images come before links, because an image is a link with
# a bang in front of it. Code spans are not here at all: they are lifted out
# before any of this runs and put back afterwards, so nothing below can read
# their contents as markup.
_MARKDOWN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\s*(?:```|~~~).*$", re.MULTILINE), ""),  # code fences
    (re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE), ""),  # ATX headings
    (re.compile(r"^\s{0,3}>\s?", re.MULTILINE), ""),  # block quotes
    # GitHub's alert syntax, which rides inside a block quote and so is left
    # behind once the quote marker goes. GHSA advisories open with it.
    (re.compile(r"\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*", re.IGNORECASE), ""),
    (re.compile(r"^\s{0,3}(?:[-*_]\s*){3,}$", re.MULTILINE), ""),  # thematic breaks
    (re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+", re.MULTILINE), ""),  # list markers
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),  # images, kept as their alt text
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),  # links, kept as their text
    (re.compile(r"\*\*(.+?)\*\*", re.DOTALL), r"\1"),  # bold
    # Underscore bold is guarded where asterisk bold is not: __init__ and
    # __reduce__ are the shape of a dunder, and an advisory about pickle or
    # prototype pollution is full of them. CommonMark would read those as
    # emphasis; a reader would not, and the identifier is what they came for.
    (re.compile(r"(?<![\w_])__(?!\s)(?![a-z]+__(?![\w_]))(.+?)(?<!\s)__(?![\w_])", re.DOTALL), r"\1"),
    # Italic, guarded against a doubled marker on either side so __proto__ does
    # not come out as _proto_ once the bold rule above has declined it.
    (re.compile(r"(?<![\w*_])(\*|_)(?![\s*_])(.+?)(?<![\s*_])\1(?![\w*_])", re.DOTALL), r"\2"),
)

#: Lifted out before the patterns above run, and restored after.
#: One line only, so a fenced block stays the fence pattern's business.
_CODE_SPAN_RE = re.compile(r"`+([^`\n]+)`+")

# Same ceiling as format_finding_description: a pathological advisory body must
# not be handed to a dozen regexes.
MAX_DESCRIPTION_CHARS = 100_000


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
def advisory_prose(text: object) -> str:
    """An advisory body as one line of plain prose.

    The pages that show a description show the opening words of it, so the
    markup is removed rather than rendered: a heading is not structure inside a
    twenty-word summary, and flattening first means the truncation that follows
    can only ever cut prose, never leave a code span or a link half-open.

    Whitespace collapses too. The source is written as paragraphs and lists,
    and every newline in it would otherwise arrive as a space in a sentence
    that reads as though a word is missing.
    """
    if not isinstance(text, str) or not text:
        return ""
    if len(text) > MAX_DESCRIPTION_CHARS:
        logger.debug("Skipping markdown flattening: length %d exceeds limit", len(text))
        return text

    # A code span is literal by definition, so its contents are set aside while
    # the rest runs. Everything an advisory puts in backticks is the thing a
    # reader is looking for: a package called *star, a header field with a #
    # in it, a path with an underscore.
    spans: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        spans.append(match.group(1))
        return f"\x00{len(spans) - 1}\x00"

    text = _CODE_SPAN_RE.sub(_stash, text)
    for pattern, replacement in _MARKDOWN_PATTERNS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)
    return " ".join(text.split())


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
        logger.debug("Skipping description formatting: length %d exceeds 100KB limit", len(description))
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
def has_compliance_failures(assessment_runs: dict[str, Any]) -> bool:
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


@register.filter
def vulnerability_findings(findings: Any) -> list[Any]:
    """Only the findings that describe vulnerabilities.

    Scanner status markers (dependency-track:no-product, osv:error) ride the
    same findings array so the run panel can explain itself, but they are not
    vulnerabilities: they must not appear in the vulnerabilities list, count
    toward its totals, or grow a Triage button.
    """
    from sbomify.apps.vulnerability_scanning.utils import is_vulnerability

    if not isinstance(findings, (list, tuple)):
        return []
    return [f for f in findings if isinstance(f, dict) and is_vulnerability(f)]


@register.filter
def vex_justification_label(value: object) -> str:
    """Human wording for a stored finding's raw VEX justification enum."""
    from sbomify.apps.vulnerability_scanning.utils import justification_label

    return justification_label(value)


@register.filter
def vulnerability_total(summary: object) -> int:
    """How many vulnerabilities a security run actually reported.

    Not ``total_findings``. That counts every row a plugin emitted, and a
    security plugin emits rows that are not vulnerabilities: a scanner that
    stood down records its own notice as one info finding, which is why the
    card had to special-case skipped runs to stop claiming a vulnerability
    nobody reported.

    Summing ``by_severity`` is what the public badge already does
    (``public_assessment_utils._is_passing``), so this brings the private card
    onto the same count rather than inventing a second one.
    """
    if not isinstance(summary, dict):
        return 0
    by_severity = summary.get("by_severity") or {}
    if not isinstance(by_severity, dict):
        return 0
    # bool subclasses int, and a stray True must not count as one vulnerability.
    return sum(value for value in by_severity.values() if isinstance(value, int) and not isinstance(value, bool))

"""Validation utilities for team-related fields."""

import re


def validate_custom_domain(domain: str) -> tuple[bool, str | None]:
    """
    Validate a custom domain for FQDN compliance.

    Args:
        domain: The domain string to validate

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.

    Rules:
        - Must be a valid FQDN (e.g., "app.example.com", "subdomain.example.co.uk")
        - No protocol (http://, https://)
        - No port numbers
        - No paths or query strings
        - No IP addresses (must be a domain name)
        - No wildcards
        - Must have at least one dot (subdomain.domain.tld)
        - Each label must be 1-63 characters
        - Total length must not exceed 253 characters
        - Labels must contain only alphanumeric characters and hyphens
        - Labels cannot start or end with hyphens
    """
    if not domain:
        return False, "Domain cannot be empty"

    # Check for leading/trailing whitespace before stripping
    if domain != domain.strip():
        return False, "Domain must not have leading or trailing whitespace"

    # Strip and lowercase for further processing
    domain = domain.strip().lower()

    # Check if empty after stripping
    if not domain:
        return False, "Domain cannot be empty"

    # Check for protocol
    if "://" in domain:
        return False, "Domain must not include protocol (http:// or https://)"

    # Check for port
    if ":" in domain:
        return False, "Domain must not include port number"

    # Check for path or query string
    if "/" in domain or "?" in domain or "#" in domain:
        return False, "Domain must not include paths or query strings"

    # Check for whitespace
    if " " in domain or "\t" in domain or "\n" in domain:
        return False, "Domain must not contain whitespace"

    # Check for wildcards
    if "*" in domain:
        return False, "Wildcard domains are not supported"

    # Check total length (RFC 1035)
    if len(domain) > 253:
        return False, "Domain name is too long (max 253 characters)"

    # Check for at least one dot (must be subdomain.domain.tld format)
    if "." not in domain:
        return False, "Domain must be a fully qualified domain name (e.g., subdomain.example.com)"

    # Check if it looks like an IP address
    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", domain):
        return False, "IP addresses are not allowed, must be a domain name"

    # Split into labels and validate each
    labels = domain.split(".")

    # Must have at least 2 labels (subdomain + domain, or domain + tld at minimum)
    if len(labels) < 2:
        return False, "Domain must have at least two parts (e.g., example.com)"

    # Check if last label is all digits (TLD cannot be all numeric)
    if labels[-1].isdigit():
        return False, "Top-level domain cannot be all numeric"

    # Validate each label
    for label in labels:
        # Check label length (RFC 1035)
        if not label:
            return False, "Domain contains empty label (consecutive dots)"
        if len(label) > 63:
            return False, f"Domain label '{label}' is too long (max 63 characters)"

        # Check label format (alphanumeric and hyphens only)
        if not re.match(r"^[a-z0-9-]+$", label):
            return False, f"Domain label '{label}' contains invalid characters (only a-z, 0-9, and - allowed)"

        # Check label doesn't start or end with hyphen
        if label.startswith("-") or label.endswith("-"):
            return False, f"Domain label '{label}' cannot start or end with a hyphen"

    return True, None

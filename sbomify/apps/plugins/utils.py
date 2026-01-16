"""Utility functions for the plugin framework.

This module provides helper functions used across the plugin framework,
including configuration hashing for reproducibility tracking and HTTP utilities.
"""

import hashlib
import json
import os
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as get_package_version

import requests

# Module-level constants
UNKNOWN_VERSION = "unknown"  # Default version when package metadata is unavailable
SBOMIFY_CONTACT_EMAIL = "hello@sbomify.com"  # Contact email for User-Agent header


def compute_config_hash(config: dict | None) -> str:
    """Compute a deterministic hash of plugin configuration.

    This hash is used to track configuration changes and determine when
    assessments need to be re-run due to configuration updates.

    The hash is computed using:
    1. JSON serialization with sorted keys for determinism
    2. Compact separators to minimize whitespace variations
    3. SHA256 for a secure, fixed-length hash

    Args:
        config: Plugin-specific configuration dictionary.
            If None or empty, returns hash of empty dict.

    Returns:
        64-character hexadecimal SHA256 hash string.

    Example:
        >>> compute_config_hash({"allowed_licenses": ["MIT", "Apache-2.0"]})
        'a1b2c3d4...'
        >>> compute_config_hash({})
        'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
        >>> compute_config_hash(None)
        'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    """
    if config is None:
        config = {}

    # Sort keys for deterministic serialization
    # Use compact separators to avoid whitespace variations
    serialized = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def compute_content_digest(content: bytes) -> str:
    """Compute SHA256 digest of content for auditability.

    This is used to track the exact SBOM content that was assessed,
    enabling verification that results correspond to specific inputs.

    Args:
        content: Raw bytes content to hash.

    Returns:
        64-character hexadecimal SHA256 hash string.
    """
    return hashlib.sha256(content).hexdigest()


# HTTP Client Utilities


def get_sbomify_version() -> str:
    """Get the current sbomify package version.

    Tries multiple sources in order:
    1. Package metadata (from pyproject.toml via importlib.metadata)
    2. SBOMIFY_VERSION environment variable (set in Dockerfile via CI/CD build args)
    3. SBOMIFY_GIT_COMMIT_SHORT environment variable (git hash fallback)
    4. UNKNOWN_VERSION constant

    The SBOMIFY_* environment variables are defined in the Dockerfile and populated
    during container builds via ARG/ENV directives from CI/CD pipelines.

    Returns:
        Version string (e.g., "0.24" or "abc1234").
    """
    try:
        return get_package_version("sbomify")
    except PackageNotFoundError:
        # Try build-time environment variables (see Dockerfile for definitions)
        version = os.environ.get("SBOMIFY_VERSION")
        if version:
            return version

        git_commit = os.environ.get("SBOMIFY_GIT_COMMIT_SHORT")
        if git_commit:
            return git_commit

        return UNKNOWN_VERSION


def get_user_agent() -> str:
    """Get the standard sbomify User-Agent string.

    The User-Agent follows the format: sbomify/{version} (hello@sbomify.com)

    This should be used for all external HTTP requests to properly
    identify sbomify as the client.

    Returns:
        User-Agent string (e.g., "sbomify/0.24 (hello@sbomify.com)").

    Example:
        >>> get_user_agent()
        'sbomify/0.24 (hello@sbomify.com)'
    """
    return f"sbomify/{get_sbomify_version()} ({SBOMIFY_CONTACT_EMAIL})"


def get_http_session() -> requests.Session:
    """Get a pre-configured requests Session with sbomify User-Agent.

    Creates a new requests.Session with the standard sbomify User-Agent
    header already set. Use this for making external HTTP requests.

    Returns:
        Configured requests.Session instance.

    Example:
        >>> session = get_http_session()
        >>> response = session.get("https://api.example.com/data")
    """
    session = requests.Session()
    session.headers.update({"User-Agent": get_user_agent()})
    return session

"""Utility functions for the plugin framework.

This module provides helper functions used across the plugin framework,
including configuration hashing for reproducibility tracking.
"""

import hashlib
import json


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

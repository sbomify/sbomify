"""PURL (Package URL) parsing and manipulation utilities.

Provides generic PURL parsing and version stripping per ECMA-427 spec.
These are pure utility functions with no Django dependencies.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import TypedDict

# PURL pattern: supports scoped packages (e.g., @scope/name) and extracts type, name, namespace, version
PURL_PATTERN = re.compile(
    r"^pkg:(?P<type>[^/]+)/(?P<name>(?:@[^@?#/]+/)?[^@?#]+)(?:@(?P<version>[^?#]+))?(?:\?(?P<qualifiers>[^#]+))?(?:#(?P<subpath>.+))?$"
)


class PURLParseError(ValueError):
    """Raised when PURL parsing fails."""


class PURLComponents(TypedDict):
    type: str
    namespace: str | None
    name: str
    version: str | None
    qualifiers: dict[str, str]
    subpath: str | None


def parse_purl(purl: str) -> PURLComponents:
    """Parse a PURL (Package URL) string into its components.

    PURL format: pkg:<type>/<namespace>/<name>@<version>?<qualifiers>#<subpath>

    Args:
        purl: The PURL string to parse

    Returns:
        Dictionary with keys: type, namespace, name, version, qualifiers, subpath

    Raises:
        PURLParseError: If the PURL is invalid
    """
    match = PURL_PATTERN.match(purl)
    if not match:
        raise PURLParseError("Invalid PURL format")

    groups = match.groupdict()

    # Parse the name which may include namespace (e.g., "namespace/name" or just "name")
    name_parts = groups["name"].split("/")
    if len(name_parts) > 1:
        namespace = "/".join(name_parts[:-1])
        name = name_parts[-1]
    else:
        namespace = None
        name = name_parts[0]

    # URL decode the components
    name = urllib.parse.unquote(name)
    if namespace:
        namespace = urllib.parse.unquote(namespace)

    version = groups.get("version")
    if version:
        version = urllib.parse.unquote(version)

    # Parse qualifiers into a dict
    qualifiers = {}
    if groups.get("qualifiers"):
        for pair in groups["qualifiers"].split("&"):
            if "=" in pair:
                key, value = pair.split("=", 1)
                qualifiers[urllib.parse.unquote(key)] = urllib.parse.unquote(value)

    return {
        "type": groups["type"],
        "namespace": namespace,
        "name": name,
        "version": version,
        "qualifiers": qualifiers,
        "subpath": urllib.parse.unquote(groups["subpath"]) if groups.get("subpath") else None,
    }


def strip_purl_version(purl: str) -> str:
    """Strip the version component from a PURL, preserving all other parts.

    Uses regex on the original string to preserve URL encoding.

    Args:
        purl: The PURL string (e.g., "pkg:npm/@scope/package@1.0.0?q=v#sub")

    Returns:
        PURL without version (e.g., "pkg:npm/@scope/package?q=v#sub")

    Raises:
        PURLParseError: If the PURL format is invalid
    """
    # Validate the PURL is parseable
    parse_purl(purl)

    # Strip version using regex on the original string to preserve encoding.
    # Negative lookbehind for '/' avoids matching scoped package '@' (e.g., @scope/name).
    return re.sub(r"(?<!/)@[^?#/]+", "", purl, count=1)

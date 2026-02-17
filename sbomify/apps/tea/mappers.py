"""
TEA (Transparency Exchange API) mapper functions.

This module provides helper functions for:
- Parsing and resolving TEI (Transparency Exchange Identifier) URNs
- Converting sbomify identifiers to TEA format
- Building TEA server URLs for workspaces

Key exports:
- TEA_API_VERSION: Current TEA API version string (e.g., "0.3.0-beta.2")
- build_tea_server_url: Constructs the TEA server root URL for a workspace
- tea_identifier_mapper: Converts sbomify ProductIdentifier to TEA format
- tea_component_identifier_mapper: Converts sbomify ComponentIdentifier to TEA format
- tea_tei_mapper: Resolves TEI URNs to sbomify entities
"""

from __future__ import annotations

import re
import urllib.parse
from typing import TYPE_CHECKING, TypedDict

from django.conf import settings
from django.db.models import Q

from sbomify.apps.core.models import Product, Release
from sbomify.apps.sboms.models import ProductIdentifier
from sbomify.apps.tea.schemas import TEAIdentifier
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.core.models import Component
    from sbomify.apps.teams.models import Team

log = getLogger(__name__)

# TEA API version
TEA_API_VERSION = "0.3.0-beta.2"

# TEI URN pattern: urn:tei:<type>:<domain-name>:<unique-identifier>
TEI_PATTERN = re.compile(r"^urn:tei:(\w+):([^:]+):(\S+)$")

# PURL pattern: pkg:<type>/<namespace>/<name>@<version>?<qualifiers>#<subpath>
# Simplified pattern that extracts type, name (with optional namespace), version
PURL_PATTERN = re.compile(
    r"^pkg:(?P<type>[^/]+)/(?P<name>[^@?#]+)(?:@(?P<version>[^?#]+))?(?:\?(?P<qualifiers>[^#]+))?(?:#(?P<subpath>.+))?$"
)


# Mapping from TEI types to sbomify ProductIdentifier types
TEI_TYPE_TO_IDENTIFIER_TYPE = {
    "purl": ProductIdentifier.IdentifierType.PURL,
    "uuid": None,  # Special case: direct product UUID lookup
    "asin": ProductIdentifier.IdentifierType.ASIN,
    "gtin": [
        ProductIdentifier.IdentifierType.GTIN_8,
        ProductIdentifier.IdentifierType.GTIN_12,
        ProductIdentifier.IdentifierType.GTIN_13,
        ProductIdentifier.IdentifierType.GTIN_14,
    ],
    "cpe": ProductIdentifier.IdentifierType.CPE,
}

# Mapping from sbomify ProductIdentifier types to TEA identifier types
IDENTIFIER_TYPE_TO_TEA = {
    ProductIdentifier.IdentifierType.PURL: "PURL",
    ProductIdentifier.IdentifierType.CPE: "CPE",
    ProductIdentifier.IdentifierType.GTIN_8: "GTIN",
    ProductIdentifier.IdentifierType.GTIN_12: "GTIN",
    ProductIdentifier.IdentifierType.GTIN_13: "GTIN",
    ProductIdentifier.IdentifierType.GTIN_14: "GTIN",
    ProductIdentifier.IdentifierType.ASIN: "ASIN",
    # Note: SKU, MPN, GS1_GPC_BRICK don't have TEA equivalents
}

# Mapping from TEA identifier type strings to sbomify ProductIdentifier types
# Used for filtering queries in API endpoints
TEA_IDENTIFIER_TYPE_MAPPING = {
    "PURL": [ProductIdentifier.IdentifierType.PURL],
    "CPE": [ProductIdentifier.IdentifierType.CPE],
    "TEI": None,  # Special case: resolved via tea_tei_mapper, not stored as ProductIdentifier
    "GTIN": [
        ProductIdentifier.IdentifierType.GTIN_8,
        ProductIdentifier.IdentifierType.GTIN_12,
        ProductIdentifier.IdentifierType.GTIN_13,
        ProductIdentifier.IdentifierType.GTIN_14,
    ],
    "ASIN": [ProductIdentifier.IdentifierType.ASIN],
}


class TEIParseError(ValueError):
    """Raised when TEI parsing fails."""


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
    """
    Parse a PURL (Package URL) string into its components.

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


def parse_tei(tei: str) -> tuple[str, str, str]:
    """
    Parse a TEI (Transparency Exchange Identifier) URN.

    TEI format: urn:tei:<type>:<domain-name>:<unique-identifier>

    Args:
        tei: The TEI URN string (URL-decoded)

    Returns:
        Tuple of (tei_type, domain_name, unique_identifier)

    Raises:
        TEIParseError: If the TEI is invalid
    """
    if len(tei) < 10:
        raise TEIParseError("Invalid TEI format")

    # URL decode if needed
    decoded_tei = urllib.parse.unquote(tei)

    if not decoded_tei.startswith("urn:tei:"):
        raise TEIParseError("Invalid TEI format")

    match = TEI_PATTERN.match(decoded_tei)
    if not match:
        raise TEIParseError("Invalid TEI format")

    return match.group(1).lower(), match.group(2), match.group(3)


def tea_tei_mapper(team: Team, tei: str) -> list[Release]:
    """
    Parse TEI URN and return matching product releases.

    TEI format: urn:tei:<type>:<domain-name>:<unique-identifier>

    Supported types:
    - purl: Direct PURL mapping (extract version from PURL if present)
    - uuid: Django UUID for product
    - asin: Direct ASIN mapping
    - gtin: Maps to GTIN_* ProductIdentifiers
    - cpe: Direct CPE mapping

    Args:
        team: The workspace/team to search within
        tei: The TEI URN string

    Returns:
        List of matching Release objects. Returns all releases for the product
        when version is not specified.

    Raises:
        TEIParseError: If the TEI is invalid
    """
    tei_type, domain_name, unique_identifier = parse_tei(tei)

    # Handle UUID type specially - direct product lookup
    if tei_type == "uuid":
        try:
            product = Product.objects.get(id=unique_identifier, team=team, is_public=True)
            return list(product.releases.all())
        except Product.DoesNotExist:
            return []

    # Get the identifier type(s) for this TEI type
    identifier_types = TEI_TYPE_TO_IDENTIFIER_TYPE.get(tei_type)
    if identifier_types is None:
        raise TEIParseError(f"Unsupported TEI type: {tei_type}")

    # For PURL type, extract version if present
    version = None
    search_value = unique_identifier

    if tei_type == "purl":
        try:
            purl_parts = parse_purl(unique_identifier)
            version = purl_parts.get("version")
            if version:
                search_value = unique_identifier.split("@")[0]
        except PURLParseError as e:
            raise TEIParseError(f"Invalid PURL in TEI: {e}") from e

    # Build the query for product identifiers (filter is_public at DB level)
    if isinstance(identifier_types, list):
        identifiers = ProductIdentifier.objects.filter(
            team=team,
            identifier_type__in=identifier_types,
            value=search_value,
            product__is_public=True,
        ).select_related("product")
    else:
        if tei_type == "purl":
            # Match exact PURL or PURL with version suffix (pkg:type/name or pkg:type/name@version)
            identifiers = ProductIdentifier.objects.filter(
                Q(value=search_value) | Q(value__startswith=search_value + "@"),
                team=team,
                identifier_type=identifier_types,
                product__is_public=True,
            ).select_related("product")
        else:
            identifiers = ProductIdentifier.objects.filter(
                team=team,
                identifier_type=identifier_types,
                value=search_value,
                product__is_public=True,
            ).select_related("product")

    products = {identifier.product for identifier in identifiers}

    # Get releases for matching products
    releases = []
    for product in products:
        product_releases = product.releases.all()

        if version:
            matching_releases = [r for r in product_releases if r.name == version]
            releases.extend(matching_releases)
        else:
            releases.extend(product_releases)

    return releases


def _build_identifier_list(identifiers_queryset) -> list[TEAIdentifier]:
    """Convert an identifiers queryset to TEA identifier format.

    Works for both ProductIdentifier and ComponentIdentifier querysets.
    GTIN_* types are merged into single "GTIN" type.
    Types without TEA equivalents are excluded.
    """
    identifiers: list[TEAIdentifier] = []
    seen: set[tuple[str, str]] = set()

    for identifier in identifiers_queryset:
        tea_type = IDENTIFIER_TYPE_TO_TEA.get(identifier.identifier_type)
        if tea_type:
            key = (tea_type, identifier.value)
            if key not in seen:
                seen.add(key)
                identifiers.append(TEAIdentifier(idType=tea_type, idValue=identifier.value))

    return identifiers


def tea_identifier_mapper(product: Product) -> list[TEAIdentifier]:
    """Convert sbomify ProductIdentifiers to TEA identifier format."""
    return _build_identifier_list(product.identifiers.all())


def tea_component_identifier_mapper(component: Component) -> list[TEAIdentifier]:
    """Convert sbomify ComponentIdentifiers to TEA identifier format."""
    return _build_identifier_list(component.identifiers.all())


def build_tea_server_url(team: Team, workspace_key: str | None = None) -> str:
    """
    Build the TEA server root URL for a workspace.

    Args:
        team: The workspace/team
        workspace_key: Optional workspace key for non-custom-domain URLs

    Returns:
        The root URL for TEA API endpoints
    """
    if team.custom_domain and team.custom_domain_validated:
        return f"https://{team.custom_domain}/tea/v1"

    base_url = settings.APP_BASE_URL
    key = workspace_key or team.key
    return f"{base_url}/public/{key}/tea/v1"

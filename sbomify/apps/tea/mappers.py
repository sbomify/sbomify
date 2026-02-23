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
from typing import TYPE_CHECKING

from django.conf import settings
from django.db.models import Q

from sbomify.apps.core.models import Product, Release
from sbomify.apps.core.purl import PURLParseError, parse_purl, strip_purl_version
from sbomify.apps.sboms.models import ProductIdentifier
from sbomify.apps.tea.schemas import TEAIdentifier
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from django.http import HttpRequest

    from sbomify.apps.core.models import Component
    from sbomify.apps.teams.models import Team

log = getLogger(__name__)

# TEA API version
TEA_API_VERSION = "0.3.0-beta.2"

# TEI URN pattern: urn:tei:<type>:<domain-name>:<unique-identifier>
TEI_PATTERN = re.compile(r"^urn:tei:(\w+):([^:]+):(\S+)$")

# SHA-256 hex digest: exactly 64 hexadecimal characters
SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


# Shared GTIN identifier types (used in both TEI and TEA mappings)
_GTIN_TYPES = [
    ProductIdentifier.IdentifierType.GTIN_8,
    ProductIdentifier.IdentifierType.GTIN_12,
    ProductIdentifier.IdentifierType.GTIN_13,
    ProductIdentifier.IdentifierType.GTIN_14,
]

# Mapping from TEI types to sbomify ProductIdentifier types
# Non-None values are always lists for uniform handling with `__in` queries.
TEI_TYPE_TO_IDENTIFIER_TYPE = {
    "purl": [ProductIdentifier.IdentifierType.PURL],
    "uuid": None,  # Special case: direct product UUID lookup
    "hash": None,  # Special case: artifact hash lookup
    "asin": [ProductIdentifier.IdentifierType.ASIN],
    "gtin": _GTIN_TYPES,
    "eanupc": _GTIN_TYPES,
    "cpe": [ProductIdentifier.IdentifierType.CPE],
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
    "GTIN": _GTIN_TYPES,
    "ASIN": [ProductIdentifier.IdentifierType.ASIN],
}


class TEIParseError(ValueError):
    """Raised when TEI parsing fails."""


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


def _resolve_hash_tei(team: Team, hash_identifier: str) -> list[Release]:
    """Resolve a hash TEI to product releases by searching artifact content hashes.

    Parses the hash identifier as <algorithm>:<value>, queries SBOM and Document
    models for matching hashes, then traverses ReleaseArtifact to find releases.

    Only SHA-256/SHA256 is supported (the only algorithm sbomify stores).

    Args:
        team: The workspace/team to search within
        hash_identifier: Hash string in format "SHA256:hexvalue" or "SHA-256:hexvalue"

    Returns:
        List of unique Release objects whose artifacts match the hash.

    Raises:
        TEIParseError: If hash format is invalid or algorithm is unsupported.
    """
    from sbomify.apps.core.models import Component, ReleaseArtifact
    from sbomify.apps.documents.models import Document
    from sbomify.apps.sboms.models import SBOM

    # Split on first colon only — hash values don't contain colons
    parts = hash_identifier.split(":", 1)
    if len(parts) != 2 or not parts[1]:
        raise TEIParseError("Invalid hash TEI format: expected <algorithm>:<value>")

    algorithm, hash_value = parts[0].upper(), parts[1]

    if algorithm not in ("SHA256", "SHA-256"):
        raise TEIParseError(f"Unsupported hash algorithm: {algorithm}")

    if not SHA256_HEX_RE.match(hash_value):
        raise TEIParseError("Invalid SHA-256 hash value: must be 64 hexadecimal characters")

    public = Component.Visibility.PUBLIC

    # Find SBOMs matching the hash
    sbom_ids = list(
        SBOM.objects.filter(
            sha256_hash=hash_value,
            component__team=team,
            component__visibility=public,
        ).values_list("id", flat=True)
    )

    # Find Documents matching the hash (check both hash fields)
    doc_ids = list(
        Document.objects.filter(
            Q(sha256_hash=hash_value) | Q(content_hash=hash_value),
            component__team=team,
            component__visibility=public,
        ).values_list("id", flat=True)
    )

    if not sbom_ids and not doc_ids:
        return []

    # Find releases via ReleaseArtifact
    release_ids = set(
        ReleaseArtifact.objects.filter(Q(sbom_id__in=sbom_ids) | Q(document_id__in=doc_ids)).values_list(
            "release_id", flat=True
        )
    )

    if not release_ids:
        return []

    return list(
        Release.objects.filter(
            id__in=release_ids,
            product__team=team,
            product__is_public=True,
        )
    )


def tea_tei_mapper(team: Team, tei: str) -> list[Release]:
    """
    Parse TEI URN and return matching product releases.

    TEI format: urn:tei:<type>:<domain-name>:<unique-identifier>

    Supported types:
    - purl: Direct PURL mapping (extract version from PURL if present)
    - uuid: Django UUID for product
    - hash: Artifact content hash lookup (SHA-256 only)
    - asin: Direct ASIN mapping
    - gtin: Maps to GTIN_* ProductIdentifiers
    - eanupc: Maps to GTIN_* ProductIdentifiers (EAN/UPC synonym)
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
    tei_type, _domain_name, unique_identifier = parse_tei(tei)

    # Handle UUID type specially - direct product lookup
    if tei_type == "uuid":
        try:
            product = Product.objects.get(id=unique_identifier, team=team, is_public=True)
            return list(product.releases.all())
        except Product.DoesNotExist:
            return []

    # Handle hash type specially - artifact hash lookup
    if tei_type == "hash":
        return _resolve_hash_tei(team, unique_identifier)

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
                search_value = strip_purl_version(unique_identifier)
        except PURLParseError as e:
            raise TEIParseError(f"Invalid PURL in TEI: {e}") from e

    # Build the query for product identifiers (filter is_public at DB level)
    # identifier_types is always a list (non-None values normalized above)
    identifiers = ProductIdentifier.objects.filter(
        team=team,
        identifier_type__in=identifier_types,
        value=search_value,
        product__is_public=True,
    ).select_related("product")

    products = {identifier.product for identifier in identifiers}

    # Single query for all releases (avoids N+1 per-product loop)
    release_qs = Release.objects.filter(product__in=products)
    if version:
        release_qs = release_qs.filter(name=version)
    return list(release_qs)


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


def build_tea_server_url(
    team: Team,
    workspace_key: str | None = None,
    request: HttpRequest | None = None,
) -> str:
    """
    Build the TEA server root URL for a workspace.

    Args:
        team: The workspace/team
        workspace_key: Optional workspace key for non-custom-domain URLs
        request: Optional HTTP request to derive scheme and host from

    Returns:
        The root URL for TEA API endpoints
    """
    if team.custom_domain and team.custom_domain_validated:
        if request:
            return f"{request.scheme}://{request.get_host()}/tea"
        return f"https://{team.custom_domain}/tea"

    base_url = settings.APP_BASE_URL.rstrip("/")
    key = workspace_key or team.key
    return f"{base_url}/public/{key}/tea"

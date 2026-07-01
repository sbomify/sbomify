from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeGuard
from uuid import uuid4

from django.conf import settings
from django.core import signing
from django.db import DatabaseError, IntegrityError, OperationalError
from django.http import HttpRequest
from django.utils import timezone

from sbomify.apps.core.models import Component, Product

# S3Client import moved to function level to support test mocking
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.sbom_format_schemas import cyclonedx_1_6 as cdx16
from sbomify.apps.teams.models import ContactProfile, Member, Team

log = logging.getLogger(__name__)

# =============================================================================
# SIGNED URL FUNCTIONALITY FOR PRIVATE COMPONENT DOWNLOADS
# =============================================================================
#
# This module provides signed URL functionality for downloading private component
# SBOMs. When generating aggregated product SBOMs that contain private components,
# we need to provide access to those components without exposing them publicly.
#
# SECURITY CONSIDERATIONS:
# - The SIGNED_URL_SALT setting should be unique per installation
# - Set SIGNED_URL_SALT environment variable in production
# - Tokens expire after SIGNED_URL_MAX_AGE seconds (default: 7 days)
# - Each token is tied to a specific SBOM and user
#
# CONFIGURATION:
# Set the SIGNED_URL_SALT environment variable to a unique value for your installation:
#   export SIGNED_URL_SALT="your-unique-salt-value-here"
#
# =============================================================================

# Signed URL constants
SIGNED_URL_MAX_AGE = 7 * 24 * 3600  # 7 days in seconds


# =============================================================================
# SHARED SBOM DATA PROCESSING UTILITIES
# =============================================================================


class SBOMDataError(Exception):
    """Custom exception for SBOM data processing errors."""

    pass


def get_sbom_data(sbom_id: str) -> tuple[SBOM, dict[str, Any]]:
    """
    Fetch SBOM instance and parsed JSON data with proper error handling.

    This function consolidates the common pattern of:
    1. Fetching SBOM from database
    2. Downloading SBOM data from S3
    3. Parsing JSON with proper error handling

    Args:
        sbom_id: The SBOM ID to fetch

    Returns:
        Tuple of (SBOM instance, parsed JSON data)

    Raises:
        SBOMDataError: If any step fails with descriptive error message
    """
    # 1) Fetch SBOM from database
    try:
        sbom_instance = SBOM.objects.select_related("component").get(id=sbom_id)
    except SBOM.DoesNotExist:
        raise SBOMDataError(f"SBOM with ID {sbom_id} not found")
    except (DatabaseError, OperationalError) as db_err:
        # Handle database connection errors gracefully
        error_msg = str(db_err).lower()
        connection_indicators = [
            "server closed the connection unexpectedly",
            "connection terminated",
            "connection reset by peer",
            "could not connect to server",
            "connection refused",
            "connection timed out",
            "network is unreachable",
        ]

        is_connection_error = any(indicator in error_msg for indicator in connection_indicators)

        if is_connection_error:
            log.warning(f"Database connection error fetching SBOM {sbom_id}: {db_err}")
            raise SBOMDataError(f"Failed to fetch SBOM data for {sbom_id}: database connection temporarily unavailable")
        else:
            log.error(f"Database error fetching SBOM {sbom_id}: {db_err}")
            raise SBOMDataError(f"Failed to fetch SBOM data for {sbom_id}: database error")

    if not sbom_instance.sbom_filename:
        raise SBOMDataError(f"SBOM ID: {sbom_id} has no sbom_filename")

    # 2) Download SBOM data from S3
    from sbomify.apps.core.object_store import S3Client

    s3_client = S3Client(bucket_type="SBOMS")
    sbom_bytes = s3_client.get_sbom_data(sbom_instance.sbom_filename)

    if not sbom_bytes:
        raise SBOMDataError(f"Failed to download SBOM {sbom_instance.sbom_filename} from S3 (empty data)")

    # 3) Decode and parse JSON
    try:
        sbom_text = sbom_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise SBOMDataError(f"SBOM {sbom_instance.sbom_filename} has encoding issues: {e}")

    try:
        sbom_data = json.loads(sbom_text)
    except json.JSONDecodeError as e:
        raise SBOMDataError(
            f"SBOM {sbom_instance.sbom_filename} content is not valid JSON. Error: {e}. "
            f"First 200 chars: {sbom_text[:200]}"
        )

    log.debug(f"SBOM {sbom_instance.sbom_filename} successfully fetched and parsed as JSON")
    return sbom_instance, sbom_data


# SBOMs are immutable (ADR-004) so caching a definitive answer (the SBOM
# was parsed and either does or doesn't name sbomify-action) is safe for a
# day. Transient read failures use a much shorter negative TTL so a brief
# S3 / decode outage doesn't lock the wrong answer in for a full day.
_SBOMIFY_ACTION_CHECK_CACHE_TTL = 24 * 3600
_SBOMIFY_ACTION_NEGATIVE_CACHE_TTL = 60


def _matches_sbomify_action_name(name: object) -> bool:
    """True for ``sbomify-action`` / ``sbomify action`` (the augmentation.py
    constant ships with a hyphen in newer releases and a space in older ones).
    Comparison is case-insensitive and whitespace/hyphen-collapsed so a future
    rename of the action keeps detection working.
    """
    if not isinstance(name, str):
        return False
    return name.replace(" ", "").replace("-", "").strip().lower() == "sbomifyaction"


def _cyclonedx_metadata_has_sbomify_action(sbom_data: Any) -> bool:
    """Detect sbomify-action in a parsed CycloneDX SBOM.

    Supports both formats sbomify-action emits (see github-action repo
    ``sbomify_action/augmentation.py``):

    - CycloneDX 1.5+: ``metadata.tools.components[]`` and
      ``metadata.tools.services[]`` (entry with ``name`` matching the
      sbomify-action constant).
    - CycloneDX 1.4 legacy: ``metadata.tools[]`` array of
      ``{name, vendor, ...}`` dicts.

    Each layer guards against unexpected JSON shapes — a malformed SBOM
    (top-level list, non-dict metadata, scalar/None entries inside the
    tools collections) returns ``False`` instead of raising
    ``AttributeError`` from a ``.get`` on a non-dict, since this runs
    on every Step 2 render and must never break the wizard.
    """
    if not isinstance(sbom_data, dict):
        return False
    metadata = sbom_data.get("metadata")
    if not isinstance(metadata, dict):
        return False
    tools = metadata.get("tools")
    if isinstance(tools, list):
        return any(isinstance(t, dict) and _matches_sbomify_action_name(t.get("name")) for t in tools)
    if isinstance(tools, dict):
        for collection_key in ("components", "services"):
            collection = tools.get(collection_key)
            if not isinstance(collection, list):
                continue
            for entry in collection:
                if isinstance(entry, dict) and _matches_sbomify_action_name(entry.get("name")):
                    return True
    return False


# SemVer-ish version: ``v?MAJOR.MINOR[.PATCH...][-prerelease][+build]``.
# The ``(\.\d+)+`` is what distinguishes a real version (``1.2.3``,
# ``v0.10``) from a fragment that just happens to start with ``v`` and a
# digit (``v2-wrapper``). Without that, ``Tool: sbomify-action-v2-wrapper-1.0.0``
# would split at ``-v2-`` and the left half would canonicalise to
# ``sbomify-action``, hiding the CTA for a different generator.
_SPDX_VERSION_SUFFIX = re.compile(r"^v?\d+(\.\d+)+([-+][\w.+-]*)?$")


def _spdx_creator_names_sbomify_action(creator: str) -> bool:
    """Return True iff a ``creationInfo.creators`` entry names sbomify-action.

    SPDX 2.x tools are emitted as ``Tool: <name>-<version>`` (see
    sbomify-action's ``augmentation.py`` — ``f"{name}-{version}"``).
    Versions in the wild include hyphenated pre-release suffixes
    (``1.2.3-rc1``, ``2.0.0-alpha.1+build.7``).

    Locate the ``-<version>`` boundary by scanning hyphens from the right
    and accepting the first one whose right-hand side matches an
    end-anchored SemVer-ish pattern. ``rightmost`` keeps as much of the
    string in the name as possible — that way ``sbomify-action-v2-wrapper-1.0.0``
    splits at the trailing ``-1.0.0`` and rejects with the name
    ``sbomify-action-v2-wrapper`` rather than the inner ``-v2-`` boundary.
    The pattern requires at least ``MAJOR.MINOR`` (so a single ``v2``
    fragment doesn't qualify as a version on its own).
    Tool entries without a version part match against the whole string.
    """
    if not creator.lower().startswith("tool:"):
        return False
    tool_name = creator.split(":", 1)[1].strip()
    # No version segment: the entire payload IS the name.
    if _matches_sbomify_action_name(tool_name):
        return True
    # Right-to-left scan: prefer splitting off as little as possible,
    # i.e. only accept the version that runs to the end of the string.
    for i in range(len(tool_name) - 1, -1, -1):
        if tool_name[i] != "-":
            continue
        suffix = tool_name[i + 1 :]
        if _SPDX_VERSION_SUFFIX.match(suffix):
            return _matches_sbomify_action_name(tool_name[:i])
    return False


def _spdx_metadata_has_sbomify_action(sbom_data: Any) -> bool:
    """Detect sbomify-action in a parsed SPDX 2.x SBOM via
    ``creationInfo.creators[]`` entries of the form
    ``"Tool: sbomify-action-<version>"``.

    Same fail-safe shape guards as the CycloneDX detector.
    """
    if not isinstance(sbom_data, dict):
        return False
    creation_info = sbom_data.get("creationInfo")
    if not isinstance(creation_info, dict):
        return False
    creators = creation_info.get("creators")
    if not isinstance(creators, list):
        return False
    for creator in creators:
        if isinstance(creator, str) and _spdx_creator_names_sbomify_action(creator):
            return True
    return False


def sbom_was_generated_by_sbomify_action(sbom: SBOM) -> bool:
    """True iff the SBOM's stored content names sbomify-action as a generator.

    Reads the SBOM JSON from S3 once and caches a definitive answer for
    ``_SBOMIFY_ACTION_CHECK_CACHE_TTL`` seconds. A transient fetch / decode
    failure caches ``False`` only for ``_SBOMIFY_ACTION_NEGATIVE_CACHE_TTL``
    so a brief S3 outage doesn't keep the CTA on for the rest of the day for
    SBOMs that would be detected once storage recovers. Returning ``False``
    on error is the fail-safe choice — a missed detection only means an
    unnecessary nudge to use the action, not data corruption.

    Cache hits/misses are treated as best-effort: django-redis without
    ``IGNORE_EXCEPTIONS`` raises on Redis outage, so ``cache.get`` and
    ``cache.set`` are wrapped to fall back to "miss / no-op". A Redis
    outage on Step 2 must not break the wizard before the S3 fail-safe
    even gets a chance to run.
    """
    from django.core.cache import cache

    cache_key = f"sbom:sbomify_action_check:{sbom.pk}"

    def _cache_get() -> Any:
        try:
            return cache.get(cache_key)
        except Exception:
            log.debug("sbomify-action cache.get failed for SBOM %s", sbom.pk, exc_info=True)
            return None

    def _cache_set(value: bool, ttl: int) -> None:
        try:
            cache.set(cache_key, value, ttl)
        except Exception:
            log.debug("sbomify-action cache.set failed for SBOM %s", sbom.pk, exc_info=True)

    cached = _cache_get()
    if cached is not None:
        return bool(cached)

    if not sbom.sbom_filename:
        # Definitive: an SBOM row without a stored blob will never name
        # sbomify-action, so keep the long TTL.
        _cache_set(False, _SBOMIFY_ACTION_CHECK_CACHE_TTL)
        return False

    try:
        from sbomify.apps.core.object_store import S3Client

        sbom_bytes = S3Client(bucket_type="SBOMS").get_sbom_data(sbom.sbom_filename)
        if not sbom_bytes:
            # Treat empty / missing as transient — the row points at a blob
            # we couldn't read, so we should retry sooner than a day.
            _cache_set(False, _SBOMIFY_ACTION_NEGATIVE_CACHE_TTL)
            return False
        sbom_data = json.loads(sbom_bytes.decode("utf-8"))
        fmt = (sbom.format or "").lower()
        if fmt == "spdx":
            result = _spdx_metadata_has_sbomify_action(sbom_data)
        else:
            # Default to CycloneDX detection — covers ``cyclonedx`` and any
            # future variant (sbom.format defaults to "spdx" but most uploads
            # are CycloneDX in practice).
            result = _cyclonedx_metadata_has_sbomify_action(sbom_data)
    except Exception:
        log.debug("sbomify-action detection failed for SBOM %s", sbom.pk, exc_info=True)
        # Transient: S3 / decode failures are not durable facts about the
        # SBOM. Cache only briefly so the next page load retries.
        _cache_set(False, _SBOMIFY_ACTION_NEGATIVE_CACHE_TTL)
        return False

    _cache_set(result, _SBOMIFY_ACTION_CHECK_CACHE_TTL)
    return result


def get_sbom_data_bytes(sbom_id: str) -> tuple[SBOM, bytes]:
    """
    Fetch SBOM instance and raw bytes data for services that need bytes.

    This function is similar to get_sbom_data() but returns the raw bytes
    instead of parsed JSON, useful for services that need the original bytes.

    Args:
        sbom_id: The SBOM ID to fetch

    Returns:
        Tuple of (SBOM instance, raw bytes data)

    Raises:
        SBOMDataError: If any step fails with descriptive error message
    """
    # 1) Fetch SBOM from database
    try:
        sbom_instance = SBOM.objects.select_related("component").get(id=sbom_id)
    except SBOM.DoesNotExist:
        raise SBOMDataError(f"SBOM with ID {sbom_id} not found")
    except (DatabaseError, OperationalError) as db_err:
        # Handle database connection errors gracefully
        error_msg = str(db_err).lower()
        connection_indicators = [
            "server closed the connection unexpectedly",
            "connection terminated",
            "connection reset by peer",
            "could not connect to server",
            "connection refused",
            "connection timed out",
            "network is unreachable",
        ]

        is_connection_error = any(indicator in error_msg for indicator in connection_indicators)

        if is_connection_error:
            log.warning(f"Database connection error fetching SBOM {sbom_id}: {db_err}")
            raise SBOMDataError(f"Failed to fetch SBOM data for {sbom_id}: database connection temporarily unavailable")
        else:
            log.error(f"Database error fetching SBOM {sbom_id}: {db_err}")
            raise SBOMDataError(f"Failed to fetch SBOM data for {sbom_id}: database error")

    if not sbom_instance.sbom_filename:
        raise SBOMDataError(f"SBOM ID: {sbom_id} has no sbom_filename")

    # 2) Download SBOM data from S3
    from sbomify.apps.core.object_store import S3Client

    s3_client = S3Client(bucket_type="SBOMS")
    sbom_bytes = s3_client.get_sbom_data(sbom_instance.sbom_filename)

    if not sbom_bytes:
        raise SBOMDataError(f"Failed to download SBOM {sbom_instance.sbom_filename} from S3 (empty data)")

    # 3) Validate that it's valid data (basic check without parsing)
    try:
        sbom_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise SBOMDataError(f"SBOM {sbom_instance.sbom_filename} has encoding issues: {e}")

    log.debug(f"SBOM {sbom_instance.sbom_filename} successfully fetched as bytes")
    return sbom_instance, sbom_bytes


def serialize_validation_errors(errors: list[Any]) -> list[Any]:
    """
    Convert Pydantic validation errors to JSON-serializable format.

    Args:
        errors: List of validation error objects

    Returns:
        List of serializable error dictionaries
    """
    errors_list = []
    for err in errors or []:
        if hasattr(err, "model_dump"):
            errors_list.append(err.model_dump())
        elif hasattr(err, "dict"):
            errors_list.append(err.dict())
        else:
            errors_list.append(err)
    return errors_list


# Lazy initialization of signer to avoid issues when Django settings aren't configured
_signer = None


def get_signer() -> signing.TimestampSigner:
    """Get the TimestampSigner instance, creating it if necessary."""
    global _signer
    if _signer is None:
        # Use configurable salt from settings
        _signer = signing.TimestampSigner(salt=settings.SIGNED_URL_SALT)
    return _signer


def _get_cyclonedx_model() -> Any:
    """Get the CycloneDX model, importing it lazily to avoid import errors."""
    try:
        from .sbom_format_schemas import cyclonedx_1_6 as cdx16

        return cdx16
    except ImportError:
        log.warning("CycloneDX library not available. Some SBOM features may be limited.")
        return None


def verify_item_access(
    request: HttpRequest,
    item: Team | Product | Component | SBOM,
    allowed_roles: list[str] | None,
) -> bool:
    """
    Verify if the user has access to the item based on the allowed roles.
    """
    if not request.user.is_authenticated:
        return False

    team_id = None
    team_key = None

    if isinstance(item, Team):
        team_id = item.id
        team_key = item.key
    elif isinstance(item, (Product, Component)):
        team_id = item.team_id
        team_key = item.team.key
    elif isinstance(item, SBOM):
        team_id = item.component.team_id
        team_key = item.component.team.key

    # Check session data first
    if team_key and "user_teams" in request.session:
        team_data = request.session["user_teams"].get(team_key)
        if team_data and "role" in team_data:
            # If no roles are specified, any role is allowed
            if allowed_roles is None:
                return True
            return team_data["role"] in allowed_roles

    # Fall back to database check
    if team_id:
        member = Member.objects.filter(user=request.user, team_id=team_id).first()
        if member:
            # If no roles are specified, any role is allowed
            if allowed_roles is None:
                return True
            return member.role in allowed_roles

    return False


@contextmanager
def temporary_sbom_files() -> Any:
    """Context manager for handling temporary SBOM files with automatic cleanup."""
    temp_files: list[Path] = []
    try:
        yield temp_files
    finally:
        # Clean up all temporary files
        for temp_file in temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
                    log.debug(f"Cleaned up temporary file: {temp_file}")
            except Exception as e:
                log.warning(f"Failed to cleanup temporary file {temp_file}: {e}")


def validate_api_endpoint(sbom_id: str) -> bool:
    """
    Validate that the API endpoint for SBOM download exists and is accessible.

    Args:
        sbom_id: The SBOM ID to validate

    Returns:
        bool: True if the endpoint should be accessible, False otherwise
    """
    try:
        # Check if the SBOM exists and has proper access controls
        sbom = SBOM.objects.select_related("component").get(pk=sbom_id)

        # Verify the SBOM has a valid file
        if not sbom.sbom_filename:
            return False

        # Check if the component is public (for public API access)
        from sbomify.apps.sboms.models import Component

        if sbom.component.visibility != Component.Visibility.PUBLIC:
            log.warning(f"API endpoint reference created for private SBOM {sbom_id}")

        return True
    except SBOM.DoesNotExist:
        log.error(f"API endpoint reference created for non-existent SBOM {sbom_id}")
        return False
    except Exception as e:
        # Handle database access issues gracefully (e.g., in tests)
        if "Database access not allowed" in str(e):
            log.debug(f"Database access not allowed for API endpoint validation of SBOM {sbom_id}")
            return True
        log.warning(f"Failed to validate API endpoint for SBOM {sbom_id}: {e}")
        return True  # Default to allowing the reference


def select_sbom_by_format(
    sboms: list["SBOM"],
    preferred_format: str = "cyclonedx",
    fallback: bool = True,
) -> SBOM | None:
    """
    Select the best SBOM from a list based on the preferred format.

    When generating aggregated SBOMs, we should prefer to link to component SBOMs
    in the same format. If the preferred format isn't available, fall back to
    any available format.

    Args:
        sboms: List of SBOM instances to choose from
        preferred_format: Preferred format ("spdx" or "cyclonedx")
        fallback: If True, return any format if preferred not found. If False, return None.

    Returns:
        The best matching SBOM, or None if no suitable SBOM found

    Example:
        >>> sboms = component.sbom_set.all()
        >>> # For SPDX output, prefer SPDX sources
        >>> sbom = select_sbom_by_format(sboms, preferred_format="spdx")
        >>> # For CycloneDX output, prefer CDX sources
        >>> sbom = select_sbom_by_format(sboms, preferred_format="cyclonedx")
    """
    if not sboms:
        return None

    # Normalize preferred format
    preferred_format = preferred_format.lower()

    # Separate SBOMs by format
    preferred_sboms = []
    other_sboms = []

    for sbom in sboms:
        sbom_format = getattr(sbom, "format", "").lower()
        if sbom_format == preferred_format:
            preferred_sboms.append(sbom)
        else:
            other_sboms.append(sbom)

    # Return preferred format if available
    if preferred_sboms:
        # Prefer the most recent one - filter items with valid created_at to avoid TypeError
        with_created_at = [s for s in preferred_sboms if s.created_at is not None]
        if with_created_at:
            return sorted(with_created_at, key=lambda s: s.created_at, reverse=True)[0]
        # Fall back to sorting by id if no created_at available
        return sorted(preferred_sboms, key=lambda s: str(s.id), reverse=True)[0]

    # Fall back to other format if allowed
    if fallback and other_sboms:
        log.debug(f"No {preferred_format} SBOM found, falling back to other format")
        with_created_at = [s for s in other_sboms if s.created_at is not None]
        if with_created_at:
            return sorted(with_created_at, key=lambda s: s.created_at, reverse=True)[0]
        # Fall back to sorting by id if no created_at available
        return sorted(other_sboms, key=lambda s: str(s.id), reverse=True)[0]

    return None


def create_component_type_mapping() -> dict[str, Any]:
    """Create mapping for component type strings to CycloneDX enums."""
    cdx16 = _get_cyclonedx_model()
    if cdx16 is None:
        return {}

    return {
        "application": cdx16.Type.application,
        "framework": cdx16.Type.framework,
        "library": cdx16.Type.library,
        "container": cdx16.Type.container,
        "platform": cdx16.Type.platform,
        "operating-system": cdx16.Type.operating_system,
        "device": cdx16.Type.device,
        "device-driver": cdx16.Type.device_driver,
        "firmware": cdx16.Type.firmware,
        "file": cdx16.Type.file,
        "machine-learning-model": cdx16.Type.machine_learning_model,
        "data": cdx16.Type.data,
        "cryptographic-asset": cdx16.Type.cryptographic_asset,
    }


def extract_component_info(component_dict: dict[str, Any]) -> tuple[str, str, Any]:
    """Extract basic component information from SBOM metadata."""
    name = component_dict.get("name", "unknown")
    component_type = component_dict.get("type", "library")
    version = component_dict.get("version")
    return name, component_type, version


def create_version_object(version: Any) -> Any:
    """Create a CycloneDX version object from various input types."""
    cdx16 = _get_cyclonedx_model()
    if cdx16 is None or not version:
        return None

    if isinstance(version, str):
        return cdx16.Version(version)
    elif isinstance(version, dict):
        return cdx16.Version(str(version))
    else:
        return cdx16.Version(str(version))


def create_external_reference(sbom_filename: str, sbom_id: str, user: Any = None) -> Any:
    """Create an external reference for the SBOM with proper validation and signed URLs for private components."""
    cdx16 = _get_cyclonedx_model()
    if cdx16 is None:
        return None

    # Validate the API endpoint exists
    if not validate_api_endpoint(sbom_id):
        log.warning(f"Creating external reference for potentially invalid SBOM endpoint: {sbom_id}")

    # Get the SBOM instance to check if it's private and generate appropriate URL
    try:
        from sbomify.apps.sboms.models import SBOM

        sbom = SBOM.objects.select_related("component").get(id=sbom_id)
        download_url = get_download_url_for_sbom(sbom, user, settings.APP_BASE_URL)
    except Exception as e:
        log.warning(f"Failed to get SBOM {sbom_id} for URL generation: {e}")
        # Fallback to regular URL
        download_url = f"{settings.APP_BASE_URL}/api/v1/sboms/{sbom_id}/download"

    # Create hash of filename for reference
    filename_hash = hashlib.sha256(sbom_filename.encode("utf-8")).hexdigest()

    return cdx16.ExternalReference(
        type=cdx16.Type3.other,
        url=download_url,
        hashes=[cdx16.Hash(alg="SHA-256", content=cdx16.HashContent(filename_hash))],
    )


_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}\Z")
# Local SPDX 2.x element id: "SPDXRef-" + letters/digits/./- (the spec's idstring
# set). No ':' so it can't corrupt a "DocumentRef-N:SPDXRef-..." external reference.
_SPDX_LOCAL_REF_RE = re.compile(r"SPDXRef-[A-Za-z0-9.-]+\Z")


def _is_sha256_hex(value: Any) -> TypeGuard[str]:
    """True iff ``value`` is a lower-case 64-hex SHA-256 digest string."""
    return isinstance(value, str) and bool(_SHA256_HEX_RE.fullmatch(value))


def spdx2_member_link(
    sbom_instance: Any, sbom_data: dict[str, Any], doc_ref_id: str
) -> tuple[dict[str, Any], str] | None:
    """Native SPDX 2.x cross-document link for an aggregate member.

    Returns ``(external_document_ref, related_spdx_element)`` for SPDX-native
    linking, or ``None`` when the member can't be linked natively (not an SPDX 2.x
    document, or missing its ``documentNamespace`` or content checksum) — the
    caller then falls back to the download-URL stub.

    The aggregate declares ``external_document_ref`` at the top level and points a
    CONTAINS relationship at ``related_spdx_element`` (``DocumentRef-x:SPDXRef-y``),
    mirroring how CycloneDX aggregation links members via externalReference. The
    checksum is the member's CONTENT hash so referential integrity is verifiable.
    """
    if not str(sbom_data.get("spdxVersion", "")).startswith("SPDX-2"):
        return None
    namespace = sbom_data.get("documentNamespace")
    checksum = getattr(sbom_instance, "sha256_hash", None)
    # namespace goes into the SPDX output (untrusted member JSON); checksum is the
    # referential-integrity digest, so require a real 64-hex SHA-256.
    if not (isinstance(namespace, str) and namespace) or not _is_sha256_hex(checksum):
        return None

    # The element the member document describes: documentDescribes, else the
    # SPDXRef-DOCUMENT DESCRIBES relationship, else the document itself. Member
    # JSON is untrusted, so accept only a valid local "SPDXRef-..." id at each
    # step — anything else (non-string, or containing a ':' that would corrupt
    # the "DocumentRef-N:SPDXRef-..." reference) falls back to SPDXRef-DOCUMENT.
    def _valid_local_ref(value: Any) -> str | None:
        return value if isinstance(value, str) and _SPDX_LOCAL_REF_RE.fullmatch(value) else None

    described: str | None = None
    describes = sbom_data.get("documentDescribes")
    if isinstance(describes, list) and describes:
        described = _valid_local_ref(describes[0])
    if described is None:
        relationships = sbom_data.get("relationships")
        if isinstance(relationships, list):
            for rel in relationships:
                if (
                    isinstance(rel, dict)
                    and rel.get("relationshipType") == "DESCRIBES"
                    and rel.get("spdxElementId") == "SPDXRef-DOCUMENT"
                ):
                    described = _valid_local_ref(rel.get("relatedSpdxElement"))
                    if described is not None:
                        break
    if described is None:
        described = "SPDXRef-DOCUMENT"

    external_document_ref = {
        "externalDocumentId": doc_ref_id,
        "spdxDocument": namespace,
        "checksum": {"algorithm": "SHA256", "checksumValue": checksum},
    }
    return external_document_ref, f"{doc_ref_id}:{described}"


def spdx2_inbound_member_dependencies(
    member_sbom_data: dict[str, Any], member_ref: str, member_digest: str, hash_to_ref: dict[str, str]
) -> list[dict[str, str]]:
    """DEPENDS_ON edges from a member to OTHER release members it actually depends on
    via cross-document references (#357 inbound resolve).

    Faithful to SPDX 2.x semantics: an ``externalDocumentRef`` only DECLARES an
    external document — the dependency is asserted by the member's ``relationships``
    graph. So an edge is emitted only when the member has a ``DEPENDS_ON``
    relationship whose ``relatedSpdxElement`` is ``DocumentRef-x:...`` AND that
    DocumentRef-x resolves, by SHA-256 checksum, to another loaded release member
    (``hash_to_ref``, keyed by ``SBOM.sha256_hash``).

    INTERNAL, digest-only: the external ``spdxDocument`` URL is NEVER dereferenced
    (SSRF / ADR-004); unresolvable refs (SHA-1, off-platform docs) are left out.
    """
    refs = member_sbom_data.get("externalDocumentRefs")
    relationships = member_sbom_data.get("relationships")
    if not isinstance(refs, list) or not isinstance(relationships, list):
        return []

    # externalDocumentId -> SHA-256 digest (SHA-256 only; sbomify stores no SHA-1).
    docid_to_digest: dict[str, str] = {}
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        checksum = ref.get("checksum")
        docid = ref.get("externalDocumentId")
        if isinstance(checksum, dict) and checksum.get("algorithm") == "SHA256" and isinstance(docid, str):
            digest = checksum.get("checksumValue")
            if _is_sha256_hex(digest):
                docid_to_digest[docid] = digest

    edges: list[dict[str, str]] = []
    seen: set[str] = set()
    for rel in relationships:
        if not isinstance(rel, dict) or rel.get("relationshipType") != "DEPENDS_ON":
            continue
        related = rel.get("relatedSpdxElement")
        if not isinstance(related, str) or ":" not in related:
            continue
        digest = docid_to_digest.get(related.split(":", 1)[0])
        if digest is None or digest == member_digest or digest in seen:
            continue
        target_ref = hash_to_ref.get(digest)
        if target_ref is None or target_ref == member_ref:
            continue
        seen.add(digest)
        edges.append({"spdxElementId": member_ref, "relatedSpdxElement": target_ref, "relationshipType": "DEPENDS_ON"})
    return edges


def _spdx3_root_element_uri(elements: Any) -> str | None:
    """The root element URI of an SPDX 3.0 member graph: the SpdxDocument's
    rootElement, else a software_Sbom, else the first software_Package.

    Tolerates malformed input (a non-list ``@graph``, non-dict elements) since
    member SBOM JSON is untrusted.
    """
    if not isinstance(elements, list):
        return None
    for element in elements:
        if isinstance(element, dict) and element.get("type") == "SpdxDocument":
            roots = element.get("rootElement")
            if isinstance(roots, list) and roots and isinstance(roots[0], str) and roots[0]:
                return roots[0]
    for type_name in ("software_Sbom", "software_Package"):
        for element in elements:
            if isinstance(element, dict) and element.get("type") == type_name:
                spdx_id = element.get("spdxId")
                if isinstance(spdx_id, str) and spdx_id:
                    return spdx_id
    return None


def spdx3_member_import(
    sbom_instance: Any, sbom_data: dict[str, Any], download_url: str
) -> tuple[dict[str, Any], str] | None:
    """Native SPDX 3.0 import-map link for an aggregate member.

    Returns ``(import_entry, root_element_uri)`` for an SPDX-3 member with a
    content checksum, or ``None`` to fall back to the local stub. The aggregate
    adds ``import_entry`` to ``SpdxDocument.import`` and references
    ``root_element_uri`` in its ``describes`` relationship; ``externalSpdxId`` and
    that referenced URI are identical so the cross-document reference resolves.
    """
    is_spdx3 = "@graph" in sbom_data or (
        str(sbom_data.get("spdxVersion", "")).startswith("SPDX-3.") and "elements" in sbom_data
    )
    if not is_spdx3:
        return None
    checksum = getattr(sbom_instance, "sha256_hash", None)
    if not _is_sha256_hex(checksum):  # goes into verifiedUsing as the integrity digest
        return None
    elements = sbom_data.get("@graph", sbom_data.get("elements", []))
    root_uri = _spdx3_root_element_uri(elements)
    if not root_uri:
        return None
    import_entry = {
        "type": "ExternalMap",
        "externalSpdxId": root_uri,
        "locationHint": download_url,
        "verifiedUsing": [{"type": "Hash", "algorithm": "sha256", "hashValue": checksum}],
    }
    return import_entry, root_uri


def spdx3_inbound_member_dependency_uris(
    member_sbom_data: dict[str, Any], member_digest: str, hash_to_uri: dict[str, str]
) -> list[str]:
    """Root URIs of OTHER release members a member actually depends on (#357 inbound
    resolve, SPDX 3.0).

    Faithful to SPDX 3.0 semantics: an ``import`` ExternalMap only establishes how
    an external URI resolves — the dependency is asserted by a ``Relationship``
    element with ``relationshipType == "dependsOn"``. So a target is returned only
    when a dependsOn relationship's ``to`` URI is covered by an import entry whose
    ``verifiedUsing`` sha256 equals another loaded member's content hash
    (``hash_to_uri``, keyed by ``SBOM.sha256_hash``).

    INTERNAL, digest-only: the ``locationHint`` URL is NEVER dereferenced (SSRF /
    ADR-004); unresolvable entries are skipped.
    """
    elements = member_sbom_data.get("@graph", member_sbom_data.get("elements", []))
    if not isinstance(elements, list):
        return []

    # external URI -> SHA-256 digest, from the SpdxDocument import maps.
    uri_to_digest: dict[str, str] = {}
    for element in elements:
        if not isinstance(element, dict) or element.get("type") != "SpdxDocument":
            continue
        imports = element.get("import")
        if not isinstance(imports, list):
            continue
        for entry in imports:
            if not isinstance(entry, dict):
                continue
            external_id = entry.get("externalSpdxId")
            if not isinstance(external_id, str):
                continue
            for hash_obj in entry.get("verifiedUsing") or []:
                if isinstance(hash_obj, dict) and hash_obj.get("algorithm") == "sha256":
                    digest = hash_obj.get("hashValue")
                    if _is_sha256_hex(digest):
                        uri_to_digest[external_id] = digest

    targets: list[str] = []
    seen: set[str] = set()
    for element in elements:
        if not isinstance(element, dict) or element.get("type") != "Relationship":
            continue
        if element.get("relationshipType") != "dependsOn":
            continue
        to = element.get("to")
        to_uris = to if isinstance(to, list) else [to]
        for uri in to_uris:
            digest = uri_to_digest.get(uri) if isinstance(uri, str) else None
            if digest is None or digest == member_digest or digest in seen:
                continue
            target_uri = hash_to_uri.get(digest)
            if target_uri is not None:
                seen.add(digest)
                targets.append(target_uri)
    return targets


def create_product_external_references(product: Product, user: Any = None) -> list[Any]:
    """Create external references from product links and documents."""
    cdx16 = _get_cyclonedx_model()
    if cdx16 is None:
        return []

    external_refs = []

    # Add product links as external references
    for link in product.links.all():
        cyclonedx_type = _get_cyclonedx_type_for_product_link(link.link_type)
        external_refs.append(
            cdx16.ExternalReference(
                type=cyclonedx_type, url=link.url, comment=link.description if link.description else None
            )
        )

    # Add documents as external references (for document components that are part of this product)
    # Get document components that are part of this product
    # Authorization is handled at the API level, so we don't filter by is_public here
    from sbomify.apps.core.models import Component

    document_components = (
        Component.objects.filter(
            component_type="document",
            products=product,
        )
        .distinct()
        .prefetch_related("document_set")
    )

    for component in document_components:
        for document in component.document_set.all():
            cyclonedx_type = _get_cyclonedx_type_for_document_type(document.document_type)
            # Use signed URL for private documents
            document_url = get_download_url_for_document(document, user=user, base_url=settings.APP_BASE_URL)
            external_refs.append(
                cdx16.ExternalReference(
                    type=cyclonedx_type,
                    url=document_url,
                    comment=document.description if document.description else None,
                )
            )

    return external_refs


def create_product_spdx_external_references(product: Product, user: Any = None) -> list[dict[str, Any]]:
    """Create SPDX external references from product links and documents."""
    external_refs = []

    # Add product links as external references
    for link in product.links.all():
        reference_category = _get_spdx_category_for_product_link(link.link_type)
        reference_type = _get_spdx_type_for_product_link(link.link_type)
        external_refs.append(
            {
                "referenceCategory": reference_category,
                "referenceType": reference_type,
                "referenceLocator": link.url,
                "comment": link.description if link.description else None,
            }
        )

    # Add documents as external references (for document components that are part of this product)
    # Get document components that are part of this product
    # Authorization is handled at the API level, so we don't filter by is_public here
    from sbomify.apps.core.models import Component

    document_components = (
        Component.objects.filter(
            component_type="document",
            products=product,
        )
        .distinct()
        .prefetch_related("document_set")
    )

    for component in document_components:
        for document in component.document_set.all():
            reference_category = document.spdx_reference_category
            reference_type = document.spdx_reference_type
            # Use signed URL for private documents
            document_url = get_download_url_for_document(document, user=user, base_url=settings.APP_BASE_URL)
            external_refs.append(
                {
                    "referenceCategory": reference_category,
                    "referenceType": reference_type,
                    "referenceLocator": document_url,
                    "comment": document.description if document.description else None,
                }
            )

    return external_refs


def _get_cyclonedx_type_for_product_link(link_type: str) -> Any:
    """Map product link types to CycloneDX external reference types."""
    cdx16 = _get_cyclonedx_model()
    if cdx16 is None:
        return None

    mapping = {
        "website": cdx16.Type3.website,
        "support": cdx16.Type3.support,
        "documentation": cdx16.Type3.documentation,
        "repository": cdx16.Type3.vcs,
        "changelog": cdx16.Type3.release_notes,
        "release_notes": cdx16.Type3.release_notes,
        "security": cdx16.Type3.security_contact,
        "issue_tracker": cdx16.Type3.issue_tracker,
        "download": cdx16.Type3.distribution,
        "chat": cdx16.Type3.chat,
        "social": cdx16.Type3.social,
        "other": cdx16.Type3.other,
    }
    return mapping.get(link_type, cdx16.Type3.other)


def _get_cyclonedx_type_for_document_type(document_type: str) -> Any:
    """Map document types to CycloneDX external reference types."""
    cdx16 = _get_cyclonedx_model()
    if cdx16 is None:
        return None

    mapping = {
        "specification": cdx16.Type3.documentation,
        "manual": cdx16.Type3.documentation,
        "readme": cdx16.Type3.documentation,
        "documentation": cdx16.Type3.documentation,
        "build-instructions": cdx16.Type3.build_meta,
        "configuration": cdx16.Type3.configuration,
        "license": cdx16.Type3.license,
        "compliance": cdx16.Type3.certification_report,
        "evidence": cdx16.Type3.evidence,
        "changelog": cdx16.Type3.release_notes,
        "release-notes": cdx16.Type3.release_notes,
        "security-advisory": cdx16.Type3.advisories,
        "vulnerability-report": cdx16.Type3.vulnerability_assertion,
        "threat-model": cdx16.Type3.threat_model,
        "risk-assessment": cdx16.Type3.risk_assessment,
        "pentest-report": cdx16.Type3.pentest_report,
        "static-analysis": cdx16.Type3.static_analysis_report,
        "dynamic-analysis": cdx16.Type3.dynamic_analysis_report,
        "quality-metrics": cdx16.Type3.quality_metrics,
        "maturity-report": cdx16.Type3.maturity_report,
        "report": cdx16.Type3.other,
        "other": cdx16.Type3.other,
    }
    return mapping.get(document_type, cdx16.Type3.other)


def _get_spdx_category_for_product_link(link_type: str) -> str:
    """Map product link types to SPDX reference categories."""
    security_types = {"security"}
    package_manager_types = {"download"}

    if link_type in security_types:
        return "SECURITY"
    elif link_type in package_manager_types:
        return "PACKAGE-MANAGER"
    else:
        return "OTHER"


def _get_spdx_type_for_product_link(link_type: str) -> str:
    """Map product link types to SPDX reference types."""
    mapping = {
        "website": "website",
        "support": "support",
        "documentation": "documentation",
        "repository": "vcs",
        "changelog": "changelog",
        "release_notes": "release-notes",
        "security": "security-contact",
        "issue_tracker": "issue-tracker",
        "download": "download",
        "chat": "chat",
        "social": "social",
        "other": "other",
    }
    return mapping.get(link_type, "other")


class ProductSBOMBuilder:
    """
    Builds product SBOM from the SBOMs of all components attached directly to the product.

    Iterates ``product.components`` (a many-to-many on the new ProductComponent table)
    and aggregates each component's SBOMs into a single CycloneDX 1.6 document with
    external references back to the originating component SBOMs.
    """

    def __init__(self, product: Product | None = None, user: Any = None) -> None:
        self.product = product
        self.user = user
        self.temp_files: list[Path] = []

    def __call__(self, *args: Any, **kwargs: Any) -> cdx16.CyclonedxSoftwareBillOfMaterialsStandard:
        # Support both (target_folder) and (product, target_folder)
        if len(args) == 1 and hasattr(self, "product") and self.product:
            target_folder = args[0]
            product = self.product
        elif len(args) == 2:
            product, target_folder = args
            self.product = product
        else:
            raise TypeError("ProductSBOMBuilder.__call__() expects (target_folder) or (product, target_folder)")

        self.target_folder = target_folder

        # Use context manager for automatic cleanup
        with temporary_sbom_files() as temp_files:
            self.temp_files = temp_files
            return self._build_sbom(product)

    def _build_sbom(self, product: Product) -> cdx16.CyclonedxSoftwareBillOfMaterialsStandard:
        """Build the product SBOM with proper database optimization and cleanup."""
        self.sbom = cdx16.CyclonedxSoftwareBillOfMaterialsStandard(
            bomFormat="CycloneDX",
            specVersion="1.6",
        )
        self.sbom.field_schema = "http://cyclonedx.org/schema/bom-1.6.schema.json"
        self.sbom.serialNumber = f"urn:uuid:{uuid4()}"
        self.sbom.version = 1

        # metadata section
        # Create main component with external references from product links and documents
        main_component = cdx16.Component(name=product.name, type=cdx16.Type.application, scope=cdx16.Scope.required)

        # Add external references from product links and documents
        external_refs = create_product_external_references(product, user=self.user)
        if external_refs:
            main_component.externalReferences = external_refs

        self.sbom.metadata = cdx16.Metadata(
            timestamp=timezone.now(),
            tools=[
                cdx16.Tool(
                    vendor="sbomify, ltd",
                    name="sbomify",
                    version=importlib.metadata.version("sbomify"),
                    externalReferences=[
                        cdx16.ExternalReference(type=cdx16.Type3.website, url="https://sbomify.com"),
                        cdx16.ExternalReference(type=cdx16.Type3.vcs, url="https://github.com/sbomify/sbomify"),
                    ],
                )
            ],
            component=main_component,
        )

        # components section - aggregate all components attached directly to the product.
        # Visibility gate: only PUBLIC + GATED components are eligible for the
        # aggregated SBOM. The download endpoint only checks ``product.is_public``
        # for the *product*; per-component filtering happens here. Without this
        # filter, any private component attached to a public product would leak
        # via the aggregated CycloneDX download.
        self.sbom.components = []

        from sbomify.apps.sboms.models import Component as SbomComponent

        public_visibilities = (SbomComponent.Visibility.PUBLIC, SbomComponent.Visibility.GATED)
        components_qs = (
            product.components.filter(visibility__in=public_visibilities)
            .select_related("team")
            .prefetch_related("sbom_set")
            .order_by("name")
        )
        for component in components_qs:
            sbom_result = self.download_component_sbom(component)  # type: ignore[arg-type]
            if sbom_result is None:
                log.warning(f"SBOM for component {component.id} not found")
                continue

            sbom_path, sbom_id = sbom_result
            log.info(f"Downloaded SBOM for component {component.id} to {sbom_path}")

            try:
                sbom_data = json.loads(sbom_path.read_text())
            except json.JSONDecodeError as e:
                log.error(f"Invalid JSON in SBOM file {sbom_path.name}: {e}")
                continue
            except Exception as e:
                log.error(f"Failed to read SBOM file {sbom_path.name}: {e}")
                continue

            cdx_component = self.get_component_metadata(sbom_path.name, sbom_data, product.name, sbom_id)
            if cdx_component is None:
                log.warning(f"Failed to get component from SBOM {sbom_path}")
                continue

            if self.sbom.components is not None:
                self.sbom.components.append(cdx_component)

        return self.sbom

    def download_component_sbom(self, component: Component) -> tuple[Path, str] | None:
        """Download the SBOM file for a component with proper cleanup tracking.

        Args:
            component: The component to download SBOM for

        Returns:
            Tuple of (Path to the downloaded SBOM file, SBOM ID), or None if no SBOM found
        """
        from sbomify.apps.core.object_store import S3Client

        # Use the prefetched SBOMs to avoid additional queries
        sboms = list(component.sbom_set.all())

        # TODO: For now, we download the first SBOM.
        # In the future, we need to support multiple SBOMs for a single component
        # and pick the latest/appropriate one.

        if not sboms:
            return None

        sbom = sboms[0]

        # Download SBOM data from S3
        s3_client = S3Client("SBOMS")
        try:
            sbom_data = s3_client.get_sbom_data(sbom.sbom_filename)
            download_path = self.target_folder / sbom.sbom_filename
            download_path.write_bytes(sbom_data)

            # Track file for cleanup
            self.temp_files.append(download_path)

            return download_path, str(sbom.id)
        except Exception as e:
            log.warning(f"Failed to download SBOM {sbom.sbom_filename}: {e}")
            return None

    def get_component_metadata(
        self, sbom_filename: str, sbom_data: dict[str, Any], product_name: str, sbom_id: str
    ) -> cdx16.Component | None:
        """Get component metadata from SBOM and create a CycloneDX 1.6 component that references the original."""
        if not self._validate_sbom_format(sbom_filename, sbom_data):
            return None

        component_dict = sbom_data.get("metadata", {}).get("component")
        if not component_dict:
            log.warning(f"SBOM {sbom_filename} does not contain component metadata")
            return None

        name, component_type, version = extract_component_info(component_dict)

        component_display_name = f"{product_name}/{name}" if product_name else name

        return self._create_cyclonedx_component(component_display_name, component_type, version, sbom_filename, sbom_id)

    def _validate_sbom_format(self, sbom_filename: str, sbom_data: dict[str, Any]) -> bool:
        """Validate that the SBOM is in CycloneDX format."""
        if sbom_data.get("bomFormat") != "CycloneDX":
            log.warning(f"SBOM {sbom_filename} is not in CycloneDX format")
            return False
        return True

    def _create_cyclonedx_component(
        self, name: str, component_type: str, version: Any, sbom_filename: str, sbom_id: str
    ) -> cdx16.Component | None:
        """Create a CycloneDX 1.6 component with proper error handling."""
        try:
            component_type_mapping = create_component_type_mapping()

            # Create the CycloneDX 1.6 component with proper enum values
            component = cdx16.Component(
                name=name,
                type=component_type_mapping.get(component_type, cdx16.Type.library),  # Default to library
                scope=cdx16.Scope.required,
            )

            # Add version if present
            version_obj = create_version_object(version)
            if version_obj:
                component.version = version_obj

            # Add external reference to the original SBOM
            component.externalReferences = [create_external_reference(sbom_filename, sbom_id, self.user)]

            return component

        except Exception as e:
            spec_version = "unknown"
            log.warning(f"Failed to create CycloneDX 1.6 component from {spec_version} SBOM {sbom_filename}: {e}")
            return None


class ReleaseSBOMBuilder:
    """
    Builds release SBOM from specific artifacts included in the release.

    This goes through only the SBOM artifacts that are explicitly included in a release
    and creates a single aggregated SBOM that represents the exact state of that release.

    Unlike ProductSBOMBuilder, this only includes the specific
    artifacts that have been selected for the release, not all available artifacts.
    """

    def __init__(self, release: Any = None, user: Any = None) -> None:
        self.release = release
        self.user = user  # User for signed URL generation
        self.temp_files: list[Path] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        # Support both (target_folder) and (release, target_folder)
        if len(args) == 1 and hasattr(self, "release") and self.release:
            target_folder = args[0]
            release = self.release
        elif len(args) == 2:
            release, target_folder = args
            self.release = release
        else:
            raise TypeError("ReleaseSBOMBuilder.__call__() expects (target_folder) or (release, target_folder)")

        self.target_folder = target_folder

        # Use context manager for automatic cleanup
        with temporary_sbom_files() as temp_files:
            self.temp_files = temp_files
            try:
                return self._build_sbom(release)
            except Exception as e:
                # Ensure cleanup happens even on error
                self._cleanup_temp_files()
                log.error(f"Error building release SBOM for {release.id}: {e}")
                raise

    def _cleanup_temp_files(self) -> None:
        """Clean up any temporary files that were created during SBOM generation."""
        for temp_file in self.temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
                    log.debug(f"Cleaned up temporary file: {temp_file}")
            except Exception as e:
                log.warning(f"Failed to clean up temporary file {temp_file}: {e}")

    def _build_sbom(self, release: Any) -> Any:
        """Build the release SBOM with proper database optimization and cleanup."""
        try:
            self.sbom = cdx16.CyclonedxSoftwareBillOfMaterialsStandard(
                bomFormat="CycloneDX",
                specVersion="1.6",
            )
            self.sbom.field_schema = "http://cyclonedx.org/schema/bom-1.6.schema.json"
            self.sbom.serialNumber = f"urn:uuid:{uuid4()}"
            self.sbom.version = 1

            # metadata section
            # Create main component with external references from product links and documents
            main_component = cdx16.Component(
                name=f"{release.product.name} - {release.name}",
                type=cdx16.Type.application,
                scope=cdx16.Scope.required,
            )

            # Add external references from the release's product links and documents
            external_refs = create_product_external_references(release.product, user=self.user)
            if external_refs:
                main_component.externalReferences = external_refs

            self.sbom.metadata = cdx16.Metadata(
                timestamp=timezone.now(),
                tools=[
                    cdx16.Tool(
                        vendor="sbomify, ltd",
                        name="sbomify",
                        version=importlib.metadata.version("sbomify"),
                        externalReferences=[
                            cdx16.ExternalReference(type=cdx16.Type3.website, url="https://sbomify.com"),
                            cdx16.ExternalReference(type=cdx16.Type3.vcs, url="https://github.com/sbomify/sbomify"),
                        ],
                    )
                ],
                component=main_component,
            )

            # components section - only include artifacts specifically in this release
            self.sbom.components = []

            # Get all SBOM artifacts in this release with optimized query
            sbom_artifacts = (
                release.artifacts.filter(sbom__isnull=False)
                .select_related("sbom__component", "sbom__component__team")
                .prefetch_related("sbom__component__team")
            )

            for artifact in sbom_artifacts:
                sbom = artifact.sbom

                # Skip if component/product access restrictions apply
                if not self._should_include_artifact(release, sbom):
                    continue

                try:
                    sbom_result = self.download_specific_sbom(sbom)
                    if sbom_result is None:
                        log.warning(f"SBOM for artifact {artifact.id} (SBOM {sbom.id}) not found")
                        continue

                    sbom_path, sbom_id = sbom_result
                    log.info(f"Downloaded SBOM for release artifact {artifact.id} to {sbom_path}")

                    try:
                        sbom_data = json.loads(sbom_path.read_text())
                    except json.JSONDecodeError as e:
                        log.error(f"Invalid JSON in SBOM file {sbom_path.name}: {e}")
                        continue
                    except Exception as e:
                        log.error(f"Failed to read SBOM file {sbom_path.name}: {e}")
                        continue

                    component = self.get_component_metadata(sbom_path.name, sbom_data, release.name, sbom_id)
                    if component is None:
                        log.warning(f"Failed to get component from SBOM {sbom_path}")
                        continue

                    self.sbom.components.append(component)

                except Exception as e:
                    log.error(f"Error processing SBOM artifact {artifact.id}: {e}")
                    # Continue with other artifacts rather than failing completely
                    continue

            return self.sbom

        except Exception as e:
            log.error(f"Error building SBOM for release {release.id}: {e}")
            raise

    def _should_include_artifact(self, release: Any, sbom: Any) -> bool:
        """Check if an SBOM artifact should be included based on access controls."""
        # For public products/releases, only include public components
        from sbomify.apps.sboms.models import Component

        if release.product.is_public:
            return bool(sbom.component.visibility == Component.Visibility.PUBLIC)

        # For private products, include all artifacts in the release
        # (access control is handled at the release level)
        return True

    def download_specific_sbom(self, sbom: Any) -> tuple[Path, str] | None:
        """Download a specific SBOM artifact with proper cleanup tracking.

        Args:
            sbom: The specific SBOM instance to download

        Returns:
            Tuple of (Path to the downloaded SBOM file, SBOM ID), or None if not found
        """
        from sbomify.apps.core.object_store import S3Client

        if not sbom.sbom_filename:
            return None

        download_path = None
        try:
            # Download SBOM data from S3
            s3_client = S3Client("SBOMS")
            sbom_data = s3_client.get_sbom_data(sbom.sbom_filename)
            download_path = self.target_folder / sbom.sbom_filename
            download_path.write_bytes(sbom_data)

            # Track file for cleanup
            self.temp_files.append(download_path)

            return download_path, str(sbom.id)
        except Exception as e:
            log.warning(f"Failed to download SBOM {sbom.sbom_filename}: {e}")
            # Clean up partial download if it exists
            if download_path and download_path.exists():
                try:
                    download_path.unlink()
                except Exception as cleanup_error:
                    log.warning(f"Failed to clean up partial download {download_path}: {cleanup_error}")
            return None

    def get_component_metadata(
        self, sbom_filename: str, sbom_data: dict[str, Any], release_name: str, sbom_id: str
    ) -> cdx16.Component | None:
        """Get component metadata from SBOM and create a CycloneDX 1.6 component that references the original."""
        try:
            # Import the constant here to avoid circular imports
            from sbomify.apps.core.models import LATEST_RELEASE_NAME

            # Validate basic SBOM format
            if not self._validate_sbom_format(sbom_filename, sbom_data):
                return None

            component_dict = sbom_data.get("metadata", {}).get("component")
            if not component_dict:
                log.warning(f"SBOM {sbom_filename} does not contain component metadata")
                return None

            # Extract component information
            name, component_type, version = extract_component_info(component_dict)

            # Add release context to the component name for better traceability
            component_display_name = f"{release_name}/{name}" if release_name != LATEST_RELEASE_NAME else name

            # Create CycloneDX component
            return self._create_cyclonedx_component(
                component_display_name, component_type, version, sbom_filename, sbom_id
            )

        except Exception as e:
            log.error(f"Error processing component metadata from {sbom_filename}: {e}")
            return None

    def _validate_sbom_format(self, sbom_filename: str, sbom_data: dict[str, Any]) -> bool:
        """Validate that the SBOM is in CycloneDX format."""
        if sbom_data.get("bomFormat") != "CycloneDX":
            log.warning(f"SBOM {sbom_filename} is not in CycloneDX format")
            return False
        return True

    def _create_cyclonedx_component(
        self, name: str, component_type: str, version: Any, sbom_filename: str, sbom_id: str
    ) -> cdx16.Component | None:
        """Create a CycloneDX 1.6 component with proper error handling."""
        try:
            component_type_mapping = create_component_type_mapping()

            # Create the CycloneDX 1.6 component with proper enum values
            component = cdx16.Component(
                name=name,
                type=component_type_mapping.get(component_type, cdx16.Type.library),  # Default to library
                scope=cdx16.Scope.required,
            )

            # Add version if present
            version_obj = create_version_object(version)
            if version_obj:
                component.version = version_obj

            # Add external reference to the original SBOM
            component.externalReferences = [create_external_reference(sbom_filename, sbom_id, self.user)]

            return component

        except Exception as e:
            spec_version = "unknown"
            log.warning(f"Failed to create CycloneDX 1.6 component from {spec_version} SBOM {sbom_filename}: {e}")
            return None


def make_download_token(sbom_id: str, user_id: str, expires_in: int = SIGNED_URL_MAX_AGE) -> str:
    """
    Generate a signed download token for an SBOM.

    Args:
        sbom_id: The ID of the SBOM to generate a token for
        user_id: The ID of the user requesting the download
        expires_in: Token expiration time in seconds (default: 7 days)

    Returns:
        A signed token string that can be used to download the SBOM
    """
    payload = {"sbom_id": sbom_id, "user_id": user_id, "expires_in": expires_in}
    return get_signer().sign_object(payload)


def verify_download_token(token: str, max_age: int = SIGNED_URL_MAX_AGE) -> dict[str, Any] | None:
    """
    Verify a signed download token and return the payload.

    Args:
        token: The signed token to verify
        max_age: Maximum age of the token in seconds (default: 7 days)

    Returns:
        Dictionary containing the payload if valid, None otherwise
    """
    try:
        payload: dict[str, Any] = get_signer().unsign_object(token, max_age=max_age)
        return payload
    except signing.BadSignature:
        log.warning(f"Invalid signature in download token: {token}")
        return None
    except signing.SignatureExpired:
        log.warning(f"Expired download token: {token}")
        return None
    except Exception as e:
        log.error(f"Error verifying download token: {e}")
        return None


# Signed URLs intentionally use internal IDs (not UUIDs). The token payload
# binds to the internal ID, and the signed download endpoint verifies this
# binding. Regular (public) download URLs use UUIDs for TEA compatibility.


def generate_signed_download_url(sbom_id: str, user_id: str, base_url: str = "") -> str:
    """
    Generate a complete signed download URL for an SBOM.

    Args:
        sbom_id: The ID of the SBOM to generate a URL for
        user_id: The ID of the user requesting the download
        base_url: Base URL for the application (optional)

    Returns:
        Complete signed download URL
    """
    token = make_download_token(sbom_id, user_id)
    return f"{base_url}/api/v1/sboms/{sbom_id}/download/signed?token={token}"


def should_use_signed_url(sbom: Any, user: Any = None) -> bool:
    """
    Determine if a signed URL should be used for downloading an SBOM.

    Args:
        sbom: The SBOM object to check
        user: The user requesting the download (optional)

    Returns:
        True if a signed URL should be used, False for regular download
    """
    # Only use signed URLs for private components
    if sbom.component.visibility != Component.Visibility.PUBLIC:
        return True

    # For public components, use regular download URLs
    return False


def get_download_url_for_sbom(sbom: Any, user: Any = None, base_url: str = "") -> str:
    """
    Get the appropriate download URL for an SBOM (signed or regular).

    Args:
        sbom: The SBOM object to get a URL for
        user: The user requesting the download (optional)
        base_url: Base URL for the application (optional)

    Returns:
        Complete download URL (signed or regular)
    """
    if should_use_signed_url(sbom, user):
        if user and user.is_authenticated:
            return generate_signed_download_url(sbom.id, str(user.id), base_url)
        else:
            # For unauthenticated users, we can't generate signed URLs
            # They shouldn't have access to private components anyway
            return f"{base_url}/api/v1/sboms/{sbom.uuid}/download"
    else:
        # Public components use regular download URLs
        return f"{base_url}/api/v1/sboms/{sbom.uuid}/download"


def make_document_download_token(document_id: str, user_id: str, expires_in: int = SIGNED_URL_MAX_AGE) -> str:
    """
    Generate a signed download token for a document.

    Args:
        document_id: The ID of the document to generate a token for
        user_id: The ID of the user requesting the download
        expires_in: Token expiration time in seconds (default: 7 days)

    Returns:
        A signed token string that can be used to download the document
    """
    payload = {"document_id": document_id, "user_id": user_id, "expires_in": expires_in}
    return get_signer().sign_object(payload)


def should_use_signed_url_for_document(document: Any, user: Any = None) -> bool:
    """
    Determine if a signed URL should be used for downloading a document.

    Args:
        document: The document object to check
        user: The user requesting the download (optional)

    Returns:
        True if a signed URL should be used, False for regular download
    """
    # Only use signed URLs for private components
    from sbomify.apps.sboms.models import Component

    if document.component.visibility != Component.Visibility.PUBLIC:
        return True

    # For public components, use regular download URLs
    return False


def get_download_url_for_document(document: Any, user: Any = None, base_url: str = "") -> str:
    """
    Get the appropriate download URL for a document (signed or regular).

    Args:
        document: The document object to get a URL for
        user: The user requesting the download (optional)
        base_url: Base URL for the application (optional)

    Returns:
        Complete download URL (signed or regular)
    """
    if should_use_signed_url_for_document(document, user):
        if user and user.is_authenticated:
            token = make_document_download_token(document.id, str(user.id))
            return f"{base_url}/api/v1/documents/{document.id}/download/signed?token={token}"
        else:
            # For unauthenticated users, we can't generate signed URLs
            # They shouldn't have access to private components anyway
            return f"{base_url}/api/v1/documents/{document.uuid}/download"
    else:
        # Public components use regular download URLs
        return f"{base_url}/api/v1/documents/{document.uuid}/download"


def get_product_sbom_package(
    product: Product,
    target_folder: Path,
    user: Any = None,
    output_format: str = "cyclonedx",
    version: str | None = None,
) -> Path:
    """
    Generates the aggregated product SBOM file using the latest release.

    This function delegates to the latest release, ensuring we get a consistent,
    curated set of artifacts that represent the current state of the product.

    SECURITY: Authorization is handled at the API/view layer. This function
    generates SBOMs for both public and private products when called by
    authorized users. For private products, only authorized team members
    can access the endpoints that call this function.

    Args:
        product: The product to generate the SBOM for
        target_folder: The folder to save the SBOM to
        user: The user requesting the SBOM (for signed URL generation)
        output_format: Output format - "cyclonedx" or "spdx" (default: "cyclonedx")
        version: Format version - e.g., "1.6", "1.7" for CDX, "2.3" for SPDX
                 If None, uses default version for the format

    Returns:
        Path to the generated SBOM file
    """
    # Import here to avoid circular imports
    from sbomify.apps.core.models import Release

    # Get or create the latest release for this product
    latest_release = Release.get_or_create_latest_release(product)

    # Delegate to release SBOM builder with format/version support
    sbom_path = get_release_sbom_package(
        release=latest_release,
        target_folder=target_folder,
        user=user,
        output_format=output_format,
        version=version,
    )

    # Rename file to use product name instead of release name
    format_lower = output_format.lower()
    extension = ".spdx.json" if format_lower == "spdx" else ".cdx.json"
    product_sbom_path = target_folder / _safe_sbom_filename(product.name, extension)

    # Move the release SBOM to product SBOM path
    sbom_path.rename(product_sbom_path)

    return product_sbom_path


def _resolve_output_version(output_format: str, version: str | None) -> str:
    """Resolve the concrete format version the builder would use.

    Defers to the shared ``builders.default_version_for_format`` (the same source
    ``get_sbom_builder`` uses) so the aggregate cache key never depends on a
    ``None`` sentinel and can't drift from the version actually built.
    """
    if version:
        return version
    from sbomify.apps.sboms.builders import default_version_for_format

    return str(default_version_for_format(output_format).value)


def _safe_sbom_filename(stem: str, extension: str) -> str:
    """Build a target filename from user-derived names (product/release) that
    cannot escape ``target_folder``.

    Product and release names are user-controlled; joining them onto a path with
    ``target_folder / name`` would allow path traversal (``..``) or absolute-path
    override if they contained separators. Neutralize path separators + null
    bytes and strip leading dots/spaces so the result is always a pure basename.
    """
    safe = stem.replace("/", "_").replace("\\", "_").replace("\x00", "").lstrip(". ")
    return f"{safe or 'sbom'}{extension}"


def compute_release_aggregate_fingerprint(release: Any) -> str:
    """Deterministic fingerprint of EVERY mutable input that shapes a public aggregate.

    Computed from the DB only (no S3 reads). A change to any of these busts the
    cache key so the next download rebuilds:

    * its PUBLIC member SBOMs (id + ``sbom_filename``, which is the sha256 of the
      bytes). Only PUBLIC members are fingerprinted — exactly the set a public
      aggregate contains — so a member flipping PUBLIC <-> PRIVATE busts the key
      while private/gated member churn does not needlessly rebuild; and
    * the release/product METADATA the builder embeds: the product + release
      names (the aggregate's top-level component name) and the product external
      references it renders from product links + identifiers. So a rename or a
      link/identifier edit also triggers a rebuild.

    Rows are ordered, and every field is length-prefixed (netstring-style) before
    hashing so user-controlled values cannot collide regardless of content — no
    reliance on a delimiter byte that a name/URL could itself contain. (ADR-004:
    member artifacts are immutable, so the filename is a faithful fingerprint.)
    """
    digest = hashlib.sha256(b"v4")

    def feed(*parts: Any) -> None:
        for part in parts:
            b = str(part).encode()
            digest.update(f"{len(b)}:".encode())
            digest.update(b)

    members = (
        release.artifacts.filter(sbom__isnull=False, sbom__component__visibility=Component.Visibility.PUBLIC)
        .order_by("sbom__id")
        .values_list("sbom__id", "sbom__sbom_filename")
    )
    for sid, fname in members.iterator():
        feed("m", sid, fname)

    # Mutable metadata embedded in the aggregate's top-level component.
    product = release.product
    feed("name", product.name, release.name)
    for ident_type, value in product.identifiers.order_by("id").values_list("identifier_type", "value").iterator():
        feed("id", ident_type, value)
    for lt, title, url, desc in (
        product.links.order_by("id").values_list("link_type", "title", "url", "description").iterator()
    ):
        feed("ln", lt, title, url, desc)

    return digest.hexdigest()


def get_release_sbom_package(
    release: Any,
    target_folder: Path,
    user: Any = None,
    output_format: str = "cyclonedx",
    version: str | None = None,
) -> Path:
    """
    Generates the aggregated release SBOM file.

    SECURITY: Authorization is handled at the API/view layer. This function
    generates SBOMs for both public and private releases when called by
    authorized users. For private releases, only authorized team members
    can access the endpoints that call this function.

    Args:
        release: The release to generate the SBOM for
        target_folder: The folder to save the SBOM to
        user: The user requesting the SBOM (for signed URL generation)
        output_format: Output format - "cyclonedx" or "spdx" (default: "cyclonedx")
        version: Format version - e.g., "1.6", "1.7" for CDX, "2.3" for SPDX
                 If None, uses default version for the format

    Returns:
        Path to the generated SBOM file
    """
    from sbomify.apps.sboms.builders import get_sbom_builder, get_supported_output_formats

    # Validate format
    supported = get_supported_output_formats()
    format_lower = output_format.lower()
    if format_lower not in supported:
        raise ValueError(f"Unsupported format: {output_format}. Supported: {list(supported.keys())}")

    # Validate version if provided
    if version and version not in supported[format_lower]:
        raise ValueError(f"Unsupported version {version} for {output_format}. Supported: {supported[format_lower]}")

    # Determine file extension based on format
    # Both CDX and SPDX builders return Pydantic models for consistent serialization
    if format_lower == "spdx":
        extension = ".spdx.json"
    else:
        extension = ".cdx.json"

    sbom_path = target_folder / _safe_sbom_filename(f"{release.product.name}-{release.name}", extension)

    # Aggregated SBOMs are expensive to build (O(N) serial member fetches) and
    # the public release/product download endpoints are unauthenticated — a
    # cheap DoS amplifier (#998). For PUBLIC products the aggregate is
    # content-addressable (only public members, which carry plain non-expiring
    # URLs), so cache it in S3 keyed by an artifact-set hash and serve it
    # directly on repeat downloads. Private releases are NOT cached: they are
    # authenticated-only (not the DoS vector) and embed short-lived signed
    # member URLs that must stay fresh.
    cache_key: str | None = None
    s3: Any = None
    # Computed unconditionally so the orphan-GC sweep below can reference it
    # without a possibly-undefined flow; it's only USED on the cached public path.
    resolved_version = _resolve_output_version(format_lower, version)
    if release.product.is_public:
        from sbomify.apps.core.object_store import S3Client

        fingerprint = compute_release_aggregate_fingerprint(release)
        cache_key = f"aggregates/release/{release.id}/{format_lower}-{resolved_version}-{fingerprint}.json"
        from botocore.exceptions import BotoCoreError, ClientError

        s3 = S3Client("SBOMS")
        # The cache is an optimization — a read failure scoped to the cache
        # (e.g. AccessDenied on the aggregates/ prefix while members stay
        # readable) falls back to a rebuild rather than 500'ing the download. A
        # MISSING BUCKET is a whole-bucket misconfiguration — the rebuild reads
        # members from the same bucket and would fail too — so let it surface
        # loudly (get_cached_aggregate only swallows NoSuchKey).
        try:
            cached = s3.get_cached_aggregate(cache_key)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "NoSuchBucket":
                raise
            log.warning("Aggregate cache read failed for %s, rebuilding: %s", cache_key, e)
            cached = None
        except BotoCoreError as e:
            # Connection errors, timeouts, etc. — the cache is best-effort, so any
            # boto read failure falls back to a rebuild rather than 500'ing.
            log.warning("Aggregate cache read failed for %s, rebuilding: %s", cache_key, e)
            cached = None
        if cached is not None:
            sbom_path.write_bytes(cached)
            return sbom_path

    # Cache miss (or private release): build the aggregate.
    builder = get_sbom_builder(
        entity_type="release",
        output_format=format_lower,
        version=version,
        entity=release,
        user=user,
    )
    sbom = builder(target_folder)
    # CycloneDX + SPDX 2.3 builders return a pydantic model; SPDX 3.0 builders
    # return a JSON-LD dict (@context/@graph) that has no model_dump_json (#357).
    if hasattr(sbom, "model_dump_json"):
        body = sbom.model_dump_json(indent=2, exclude_none=True, exclude_unset=True, by_alias=True).encode()
    else:
        body = json.dumps(sbom, indent=2).encode()
    sbom_path.write_bytes(body)

    # Only cache a COMPLETE build. The builders skip a member on an S3 fetch
    # error (non-fatal, returns a partial aggregate); caching that would freeze
    # an incomplete document under this artifact-set hash indefinitely, so a
    # transient blip would persist. Cache writes are best-effort — a failure to
    # store must not fail the download.
    if cache_key is not None and s3 is not None:
        if getattr(builder, "had_member_fetch_error", False):
            log.warning("Skipping aggregate cache for %s: build had member fetch errors", cache_key)
        else:
            try:
                s3.put_cached_aggregate(cache_key, body)
            except Exception as e:
                log.warning("Aggregate cache write failed for %s (served anyway): %s", cache_key, e)
            else:
                # GC orphaned aggregates. When the artifact set or metadata changes
                # the fingerprint changes, leaving the previous key behind. Sweep
                # siblings under the SAME format+version prefix and drop all but the
                # key just written — scoping to format_lower-resolved_version keeps
                # other formats/versions intact. Best-effort: a sweep failure must
                # never fail the download.
                gc_prefix = f"aggregates/release/{release.id}/{format_lower}-{resolved_version}-"
                try:
                    for stale_key in s3.list_cached_aggregates(gc_prefix):
                        if stale_key != cache_key:
                            s3.delete_cached_aggregate(stale_key)
                except Exception as e:
                    log.warning("Aggregate cache GC failed for prefix %s: %s", gc_prefix, e)

    return sbom_path


def create_default_component_metadata(
    user: Any, team_id: int, custom_metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Create default metadata for a component.

    Args:
        user: The user creating the component
        team_id: The team ID
        custom_metadata: Optional custom metadata to merge with defaults

    Returns:
        dict: The component metadata (legacy format for backward compatibility)
    """
    from allauth.socialaccount.models import SocialAccount

    # Get user and team information
    social_account = SocialAccount.objects.filter(user=user, provider="keycloak").first()
    user_metadata = social_account.extra_data.get("user_metadata", {}) if social_account else {}

    # Only populate if we have actual user metadata
    default_metadata: dict[str, Any] = {}

    # Only add supplier info if we have company data from Keycloak
    company_name = user_metadata.get("company")
    if company_name:
        supplier_url = user_metadata.get("supplier_url")
        default_metadata["supplier"] = {"name": company_name, "url": [supplier_url] if supplier_url else None}
        default_metadata["organization"] = {
            "name": company_name,
            "contact": {
                "name": f"{user.first_name} {user.last_name}".strip(),
                "email": user.email,
            },
        }

    # Add author and supplier info if we have a real user name and email
    if user.first_name and user.last_name and user.email:
        user_name = f"{user.first_name} {user.last_name}".strip()

        default_metadata["authors"] = [
            {
                "name": user_name,
                "email": user.email,
            }
        ]

        # If no company-specific supplier was set above, use user info
        if "supplier" not in default_metadata:
            default_metadata["supplier"] = {"name": user_name, "url": None}

    # If custom metadata is provided, merge it with defaults
    if custom_metadata:
        component_metadata = custom_metadata.copy()

        # Add default author/organization info if not provided
        if "authors" not in component_metadata:
            component_metadata["authors"] = default_metadata["authors"]

        if "organization" not in component_metadata:
            component_metadata["organization"] = default_metadata["organization"]

        if "supplier" not in component_metadata:
            component_metadata["supplier"] = default_metadata["supplier"]

        return component_metadata

    return default_metadata


def populate_component_metadata_native_fields(
    component: Any, user: Any, custom_metadata: dict[str, Any] | None = None
) -> None:
    """
    Populate component native fields with default metadata.

    Args:
        component: The component instance to populate
        user: The user creating the component
        custom_metadata: Optional custom metadata to merge with defaults
    """
    from allauth.socialaccount.models import SocialAccount

    # Get user and team information
    social_account = SocialAccount.objects.filter(user=user, provider="keycloak").first()
    user_metadata = social_account.extra_data.get("user_metadata", {}) if social_account else {}

    default_profile = None
    if custom_metadata is None:
        default_profile = (
            ContactProfile.objects.filter(team_id=component.team_id, is_default=True)
            .prefetch_related("entities", "entities__contacts")
            .first()
        )
        if default_profile:
            component.contact_profile = default_profile
            # Access fields via first entity (3-level hierarchy)
            first_entity = default_profile.entities.first()
            if first_entity:
                if first_entity.name:
                    component.supplier_name = first_entity.name
                if first_entity.website_urls:
                    component.supplier_url = first_entity.website_urls
                if first_entity.address:
                    component.supplier_address = first_entity.address

                # Supplier contacts from entity.contacts
                component.supplier_contacts.all().delete()
                for order, contact in enumerate(first_entity.contacts.all()):
                    component.supplier_contacts.create(
                        name=contact.name,
                        email=contact.email,
                        phone=contact.phone,
                        order=order,
                    )

            # Copy authors from profile to component
            # Authors are now entity contacts with is_author=True
            component.authors.all().delete()
            order = 0
            for entity in default_profile.entities.all():
                for contact in entity.contacts.filter(is_author=True):
                    component.authors.create(
                        name=contact.name,
                        email=contact.email,
                        phone=contact.phone,
                        order=order,
                    )
                    order += 1
    else:
        component.contact_profile = None

    # Set supplier information
    if not component.contact_profile_id:
        company_name = user_metadata.get("company")
        if company_name:
            component.supplier_name = company_name
            supplier_url = user_metadata.get("supplier_url")
            if supplier_url:
                component.supplier_url = [supplier_url]
        elif user.first_name and user.last_name:
            # Use user name as supplier if no company
            component.supplier_name = f"{user.first_name} {user.last_name}".strip()

    # Create default author from user if no authors exist yet.
    # This can happen if the contact profile had no authors, if no profile was used,
    # or if custom_metadata was provided but did not supply any authors.
    if not component.authors.exists() and user.first_name and user.last_name and user.email:
        user_name = f"{user.first_name} {user.last_name}".strip()
        component.authors.create(
            name=user_name,
            email=user.email,
        )

    # Handle custom metadata if provided
    if custom_metadata:
        # Override with custom supplier info
        supplier = custom_metadata.get("supplier", {})
        if supplier.get("name"):
            component.supplier_name = supplier["name"]
        if supplier.get("url"):
            component.supplier_url = supplier["url"]
        if supplier.get("address"):
            component.supplier_address = supplier["address"]

        # Create custom supplier contacts
        for contact_data in supplier.get("contacts", []):
            if contact_data.get("name"):
                component.supplier_contacts.create(
                    name=contact_data["name"],
                    email=contact_data.get("email"),
                    phone=contact_data.get("phone"),
                )

        # Override with custom authors
        authors = custom_metadata.get("authors", [])
        if authors:
            # Clear default author if custom authors are provided
            component.authors.all().delete()
            for author_data in authors:
                if author_data.get("name"):
                    component.authors.create(
                        name=author_data["name"],
                        email=author_data.get("email"),
                        phone=author_data.get("phone"),
                    )

        # Set lifecycle phase
        if custom_metadata.get("lifecycle_phase"):
            component.lifecycle_phase = custom_metadata["lifecycle_phase"]

        # Handle licenses
        licenses = custom_metadata.get("licenses", [])
        if licenses:
            # Clear any existing licenses
            component.licenses.all().delete()

            # Create new licenses
            for order, license_data in enumerate(licenses):
                if isinstance(license_data, str):
                    # Check if it's a license expression (contains operators)
                    from sbomify.apps.core.licensing_utils import is_license_expression

                    if is_license_expression(license_data):
                        component.licenses.create(
                            license_type="expression",
                            license_id=license_data,
                            order=order,
                        )
                    else:
                        component.licenses.create(
                            license_type="spdx",
                            license_id=license_data,
                            order=order,
                        )
                elif isinstance(license_data, dict):
                    # Handle custom licenses
                    if "name" in license_data:
                        component.licenses.create(
                            license_type="custom",
                            license_name=license_data["name"],
                            license_url=license_data.get("url"),
                            license_text=license_data.get("text"),
                            bom_ref=license_data.get("bom_ref"),
                            order=order,
                        )
                    elif "id" in license_data:
                        # Handle SPDX license objects
                        component.licenses.create(
                            license_type="spdx",
                            license_id=license_data["id"],
                            bom_ref=license_data.get("bom_ref"),
                            order=order,
                        )


# Shared by the upload API (#1042) and the CBOM backfill command (#1069); kept here in
# the neutral utils module so neither imports the web/API layer for them.
_SBOM_UNIQUE_CONSTRAINT = "sboms_sbom_unique_component_version_format_qualifiers_bom_type"


def _is_crypto_component(component: Any) -> bool:
    """A CycloneDX component is a crypto asset if typed as one or carrying cryptoProperties."""
    return isinstance(component, dict) and (
        component.get("type") == "cryptographic-asset" or "cryptoProperties" in component
    )


def _is_cbom(sbom_data: dict[str, Any]) -> bool:
    """True when a CycloneDX document declares cryptographic-asset content (a CBOM).

    Checks both the top-level ``components`` array and ``metadata.component`` (which
    is itself a Component and may carry the crypto indicators on its own).
    """
    components = sbom_data.get("components")
    if isinstance(components, list) and any(_is_crypto_component(c) for c in components):
        return True
    metadata = sbom_data.get("metadata")
    return isinstance(metadata, dict) and _is_crypto_component(metadata.get("component"))


def _is_duplicate_integrity_error(exc: IntegrityError) -> bool:
    """Check if an IntegrityError is for the SBOM uniqueness constraint.

    Postgres path: checks diag.constraint_name, then SQLSTATE 23505 with
    constraint name in the message.
    SQLite path: checks for "UNIQUE constraint failed" with the relevant columns.
    """
    cause = exc.__cause__
    if cause is not None:
        # Try PostgreSQL diagnostics first (most precise)
        diag = getattr(cause, "diag", None)
        if diag is not None:
            diag_constraint: str | None = getattr(diag, "constraint_name", None)
            if diag_constraint == _SBOM_UNIQUE_CONSTRAINT:
                return True

        pgcode: str | None = getattr(cause, "pgcode", None)
        if pgcode == "23505":
            return _SBOM_UNIQUE_CONSTRAINT in str(exc).lower()

    msg = str(exc).lower()

    # Postgres fallback (no __cause__ or missing diag)
    if _SBOM_UNIQUE_CONSTRAINT in msg:
        return True

    # SQLite: "UNIQUE constraint failed: <db_table>.component_id, <db_table>.version, ..."
    # Derive the table from the model so it can't drift (it's "sboms_sboms", not "sboms_sbom").
    table = SBOM._meta.db_table
    return "unique constraint failed" in msg and all(
        f"{table}.{col}" in msg for col in ("component_id", "version", "format", "qualifiers", "bom_type")
    )

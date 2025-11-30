import collections.abc
import ipaddress
import logging
import string
import uuid
from dataclasses import dataclass
from secrets import token_urlsafe
from typing import Any

from django.http import HttpRequest

logger = logging.getLogger(__name__)

TRANSLATION_STRING = "abcdefghij"


def number_to_random_token(value: int) -> str:
    """
    Convert an integer to a random token.
    """
    tok_prefix = token_urlsafe(6)
    tok_suffix = "".join(TRANSLATION_STRING[int(c)] for c in str(value))

    return f"{tok_prefix}{tok_suffix}"


def token_to_number(token: str) -> int:
    """
    Convert a random token to an integer.

    Args:
        token: The token string to convert

    Returns:
        The integer value encoded in the token

    Raises:
        ValueError: If token is too short or contains invalid characters
    """
    if len(token) < 9:
        raise ValueError("Token is too short")

    try:
        return int("".join(str(TRANSLATION_STRING.index(c)) for c in token[8:]))
    except ValueError:
        raise ValueError("Invalid token format")


def get_current_team_id(request: HttpRequest) -> int | None:
    """
    Get the team ID for the current team from the request.

    Request contains team keys which can be translated into team IDs.

    If no current team is found in the request session, return None.
    """
    team_key = request.session.get("current_team", {}).get("key")
    if team_key is None:
        return None

    return token_to_number(team_key)


def is_trusted_proxy(ip: str) -> bool:
    """
    Check if an IP address is a trusted proxy.

    Defaults to checking against private IP ranges.
    """
    if not ip:
        return False

    try:
        ip_obj = ipaddress.ip_address(ip)
        return ip_obj.is_private or ip_obj.is_loopback
    except ValueError:
        return False


def get_client_ip(request: HttpRequest) -> str | None:
    """
    Get the client IP address from the request.

    This function attempts to find the correct client IP by:
    1. Checking the immediate REMOTE_ADDR.
    2. If REMOTE_ADDR is a trusted proxy (private/loopback), it inspects
       proxy headers like CF-Connecting-IP and X-Real-IP.

    It prioritizes headers that are likely set by trusted infrastructure
    (Cloudflare or Caddy) and avoids X-Forwarded-For to prevent spoofing.
    """
    remote_addr = request.META.get("REMOTE_ADDR")

    # If the request comes from an untrusted source (public Internet),
    # we trust REMOTE_ADDR as the client IP.
    if not is_trusted_proxy(remote_addr):
        return remote_addr

    # If we are here, REMOTE_ADDR is a trusted proxy (e.g. Caddy, Load Balancer).
    # We can inspect headers that our trusted proxy passes or sets.

    # Cloudflare (CF-Connecting-IP)
    # Caddy should be configured to only pass this if it trusts Cloudflare.
    cf_connecting_ip = request.META.get("HTTP_CF_CONNECTING_IP")
    if cf_connecting_ip:
        return cf_connecting_ip

    # X-Real-IP
    # Caddy sets this to the resolved client IP using its 'trusted_proxies' logic.
    x_real_ip = request.META.get("HTTP_X_REAL_IP")
    if x_real_ip:
        return x_real_ip

    # Fallback to REMOTE_ADDR if no better info is available from trusted proxy
    return remote_addr


def dict_update(d, u):
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = dict_update(d.get(k, {}), v)
        else:
            d[k] = v

    return d


def set_values_if_not_empty(object_in, **kwargs):
    for attribute_name, attribute_value in kwargs.items():
        if attribute_value:
            setattr(object_in, attribute_name, attribute_value)


@dataclass
class ExtractSpec:
    field: str
    required: bool = True
    default: Any | None = None
    error_message: str | None = None
    rename_to: str | None = None


def obj_extract(obj_in, fields: list[ExtractSpec]) -> dict:
    """
    Extract fields from an object.

    :param obj_in: The object to extract fields from.
    :param fields: A list of ExtractSpec objects.
    :return: A dictionary of extracted fields.
    """
    result = {}

    for field in fields:
        # if field.field contains a dot, it means we need to extract a nested field

        field_parts = field.field.split(".")
        value = obj_in

        for part in field_parts:
            value = getattr(value, part, None)

            if value is None:
                if field.required:
                    if field.error_message:
                        raise ValueError(field.error_message)
                    else:
                        raise ValueError(f"Field '{field.field}' is required.")

                elif field.default is not None:
                    if field.rename_to:
                        result[field.rename_to] = field.default
                    else:
                        result[field.field] = field.default

                    break

                else:
                    break

        if value is not None:
            if field.rename_to:
                result[field.rename_to] = value
            else:
                result[field.field] = value

    return result


def generate_id() -> str:
    """Generate a globally unique ID that is 12 characters long.

    The ID will:
    - Contain only alphanumeric characters (0-9, a-z, A-Z)
    - Always start with a letter
    - Be 12 characters long
    - Have sufficient entropy to avoid collisions (72 bits)

    Returns:
        str: A unique alphanumeric ID, 12 characters long.
    """
    # Characters for base62 encoding (0-9, a-z, A-Z)
    CHARS = string.ascii_letters + string.digits  # Letters first to bias towards letters

    while True:
        # Generate 9 random bytes (72 bits) of entropy
        # This gives us ~4.7e21 possible values - more than enough for uniqueness
        random_int = int.from_bytes(uuid.uuid4().bytes[:9], "big")

        # Convert to base62
        base62 = ""
        temp_int = random_int
        while temp_int:
            temp_int, remainder = divmod(temp_int, 62)
            base62 = CHARS[remainder] + base62

        # Pad with 'a' if needed to reach exactly 12 chars
        base62 = base62.rjust(12, "a")

        # If longer than 12 chars, try again with new random value
        if len(base62) > 12:
            continue

        # Ensure first character is a letter by replacing it if it's not
        if not base62[0].isalpha():
            # Use last 6 bits of the random_int to select a letter (0-51)
            letter_idx = random_int % 52
            base62 = string.ascii_letters[letter_idx] + base62[1:]

        return base62


def get_team_id_from_session(request) -> str | None:
    """
    Standardized way to get team ID from request session.

    This function handles the different session key formats that may exist
    and provides consistent team ID retrieval across the application.

    Args:
        request: The HTTP request object

    Returns:
        str | None: The team ID as string, or None if not found
    """
    session = request.session
    current_team = session.get("current_team")

    if not current_team:
        return None

    # Handle different session key formats
    if "team_id" in current_team:
        return str(current_team["team_id"])
    elif "id" in current_team:
        return str(current_team["id"])
    elif "key" in current_team:
        # Convert token to team ID
        try:
            team_id = token_to_number(current_team["key"])
            return str(team_id)
        except (ValueError, TypeError):
            return None

    return None


def verify_item_access(
    request: HttpRequest,
    item: Any,  # Team | Product | Project | Component | SBOM
    allowed_roles: list | None,
) -> bool:
    """
    Verify if the user has access to the item based on the allowed roles.

    This function works with any model that has a team relationship.
    For Team objects, it uses the team directly.
    For other objects, it looks for team_id or team.key attributes.
    """
    if not request.user.is_authenticated:
        return False

    team_id = None
    team_key = None

    # Import here to avoid circular imports
    from sbomify.apps.teams.models import Member

    # Handle Team objects directly
    if hasattr(item, "_meta") and item._meta.label == "teams.Team":
        team_id = item.id
        team_key = item.key
    # Handle objects with team relationship
    elif hasattr(item, "team_id"):
        team_id = item.team_id
        if hasattr(item, "team"):
            team_key = item.team.key
    elif hasattr(item, "team"):
        team_id = item.team.id if hasattr(item.team, "id") else None
        team_key = item.team.key if hasattr(item.team, "key") else None
    # Handle SBOM objects (component.team relationship)
    elif hasattr(item, "component") and hasattr(item.component, "team_id"):
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


def add_artifact_to_release(release, sbom=None, document=None, allow_replacement=False):
    """
    Add an artifact (SBOM or Document) to a release.

    This function handles the logic for adding artifacts to releases, including
    replacement logic for artifacts of the same type/format from the same component.

    Args:
        release: The Release object to add the artifact to
        sbom: The SBOM object to add (optional)
        document: The Document object to add (optional)
        allow_replacement: If True, allows replacing existing artifacts of same format/type.
                          If False, rejects duplicates with an error.

    Returns:
        dict: Contains 'created', 'replaced', 'artifact' keys with information about the operation
    """
    from sbomify.apps.core.models import ReleaseArtifact

    if not sbom and not document:
        raise ValueError("Either sbom or document must be provided")
    if sbom and document:
        raise ValueError("Cannot provide both sbom and document")

    # Check if artifact already exists in this release
    if sbom:
        existing = ReleaseArtifact.objects.filter(release=release, sbom=sbom).first()
    else:
        existing = ReleaseArtifact.objects.filter(release=release, document=document).first()

    if existing:
        # Artifact already exists - no action needed
        return {
            "created": False,
            "replaced": False,
            "artifact": existing,
            "error": "Artifact already exists in this release",
        }

    # Handle duplicate formats based on allow_replacement setting
    if sbom:
        # For SBOMs: check for existing SBOM of same format from same component
        existing_sbom_artifact = ReleaseArtifact.objects.filter(
            release=release, sbom__component=sbom.component, sbom__format=sbom.format
        ).first()

        if existing_sbom_artifact:
            if not allow_replacement:
                return {
                    "created": False,
                    "replaced": False,
                    "artifact": None,
                    "error": (
                        f"Release already contains an SBOM of format {sbom.format} from component {sbom.component.name}"
                    ),
                }
            else:
                # Replace the existing artifact
                replaced_info = {
                    "replaced_sbom": existing_sbom_artifact.sbom.name,
                    "replaced_format": existing_sbom_artifact.sbom.format,
                    "new_sbom": sbom.name,
                    "component": sbom.component.name,
                }
                existing_sbom_artifact.delete()
                new_artifact = ReleaseArtifact.objects.create(release=release, sbom=sbom)
                return {"created": False, "replaced": True, "artifact": new_artifact, "replaced_info": replaced_info}

    else:  # document
        # For Documents: check for existing document of same type from same component
        existing_doc_artifact = ReleaseArtifact.objects.filter(
            release=release, document__component=document.component, document__document_type=document.document_type
        ).first()

        if existing_doc_artifact:
            if not allow_replacement:
                return {
                    "created": False,
                    "replaced": False,
                    "artifact": None,
                    "error": (
                        f"Release already contains {document.document_type} document "
                        f"from component {document.component.name}"
                    ),
                }
            else:
                # Replace the existing artifact
                replaced_info = {
                    "replaced_document": existing_doc_artifact.document.name,
                    "replaced_type": existing_doc_artifact.document.document_type,
                    "new_document": document.name,
                    "component": document.component.name,
                }
                existing_doc_artifact.delete()
                new_artifact = ReleaseArtifact.objects.create(release=release, document=document)
                return {"created": False, "replaced": True, "artifact": new_artifact, "replaced_info": replaced_info}

    # Create the new artifact (no duplicates found)
    if sbom:
        new_artifact = ReleaseArtifact.objects.create(release=release, sbom=sbom)
    else:
        new_artifact = ReleaseArtifact.objects.create(release=release, document=document)

    return {"created": True, "replaced": False, "artifact": new_artifact, "replaced_info": None}


def create_release_download_response(release):
    """
    Create an HTTP response for downloading a release's SBOM content.

    Args:
        release: The Release object to create download response for

    Returns:
        HttpResponse: Response with the release SBOM content for download
    """
    import tempfile
    from pathlib import Path

    from django.http import HttpResponse, JsonResponse

    # Get all SBOM artifacts in the release
    sbom_artifacts = release.artifacts.filter(sbom__isnull=False).select_related("sbom")

    if not sbom_artifacts.exists():
        return JsonResponse({"detail": "Error generating release SBOM"}, status=500)

    try:
        # Use the proper SBOM package generator
        from sbomify.apps.sboms.utils import get_release_sbom_package

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            # Note: In this context, we don't have access to the requesting user,
            # so we pass None. This function is mainly for internal use.
            sbom_file_path = get_release_sbom_package(release, temp_path, user=None)

            # Read the generated SBOM file
            with open(sbom_file_path, "r") as f:
                sbom_content = f.read()

            response = HttpResponse(sbom_content, content_type="application/json")
            response["Content-Disposition"] = f"attachment; filename={release.product.name}-{release.name}.cdx.json"

            return response

    except Exception as e:
        logger.exception(f"Error generating release SBOM: {str(e)}")
        return JsonResponse({"detail": "Error generating release SBOM"}, status=500)

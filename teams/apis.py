from pathlib import Path

from django.conf import settings
from django.http import HttpRequest
from ninja import File, Router
from ninja.files import UploadedFile
from ninja.security import django_auth
from pydantic import BaseModel

from access_tokens.auth import PersonalAccessTokenAuth
from core.object_store import S3Client
from core.schemas import ErrorResponse
from core.utils import token_to_number
from sbomify.logging import getLogger

from .models import Member, Team
from .schemas import BrandingInfo, BrandingInfoWithUrls

logger = getLogger(__name__)

router = Router(tags=["teams"], auth=(PersonalAccessTokenAuth(), django_auth))


class FieldValue(BaseModel):
    value: str | bool | None


@router.get("/{team_key}/branding", response={200: BrandingInfoWithUrls, 400: ErrorResponse, 404: ErrorResponse})
def get_team_branding(request: HttpRequest, team_key: str):
    """Get team branding information."""
    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return 400, {"detail": "Invalid team key"}

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, {"detail": "Team not found"}

    branding_info = BrandingInfo(**team.branding_info)
    response_data = {
        **team.branding_info,
        "icon_url": branding_info.brand_icon_url,
        "logo_url": branding_info.brand_logo_url,
    }
    return 200, BrandingInfoWithUrls(**response_data)


@router.patch(
    "/{team_key}/branding/{field}",
    response={200: BrandingInfoWithUrls, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def update_team_branding(
    request: HttpRequest,
    team_key: str,
    field: str,
    data: FieldValue,
):
    """Update a single branding field."""

    # Validate field name
    valid_fields = {"brand_color", "accent_color", "prefer_logo_over_icon", "icon", "logo"}
    if field not in valid_fields:
        return 400, {"detail": f"Invalid field. Must be one of: {', '.join(valid_fields)}"}

    try:
        team = Team.objects.get(pk=token_to_number(team_key))
    except (ValueError, Team.DoesNotExist):
        logger.warning(f"Team not found: {team_key}")
        return 404, {"detail": "Team not found"}

    if not Member.objects.filter(user=request.user, team=team, role="owner").exists():
        logger.warning(f"User {request.user.username} is not owner of team {team_key}")
        return 403, {"detail": "Only allowed for owners"}

    current_branding = BrandingInfo(**team.branding_info)
    update_data = current_branding.dict()

    s3_client = S3Client("MEDIA")

    # Handle file deletions
    if field in ["icon", "logo"] and data.value is None and update_data.get(field):
        s3_client.delete_object(settings.AWS_MEDIA_STORAGE_BUCKET_NAME, update_data[field])
        update_data[field] = ""
    else:
        update_data[field] = data.value

    team.branding_info = update_data
    team.save()

    response_data = {
        **team.branding_info,
        "icon_url": current_branding.brand_icon_url,
        "logo_url": current_branding.brand_logo_url,
    }
    return 200, BrandingInfoWithUrls(**response_data)


@router.post(
    "/{team_key}/branding/upload/{file_type}",
    response={200: BrandingInfoWithUrls, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def upload_branding_file(
    request: HttpRequest,
    team_key: str,
    file_type: str,
    file: File[UploadedFile],
):
    """Upload team branding files (icon or logo)."""
    if file_type not in ["icon", "logo"]:
        return 400, {"detail": "Invalid file type. Must be 'icon' or 'logo'"}

    try:
        team = Team.objects.get(pk=token_to_number(team_key))
    except (ValueError, Team.DoesNotExist):
        return 404, {"detail": "Team not found"}

    if not Member.objects.filter(user=request.user, team=team, role="owner").exists():
        return 403, {"detail": "Only allowed for owners"}

    current_branding = BrandingInfo(**team.branding_info)
    update_data = current_branding.dict()
    s3_client = S3Client("MEDIA")

    # Delete existing file if present
    if update_data.get(file_type):
        s3_client.delete_object(settings.AWS_MEDIA_STORAGE_BUCKET_NAME, update_data[file_type])

    # Upload new file
    file_ext = Path(request.FILES["file"].name).suffix
    filename = f"{team.key}_{file_type}{file_ext}"
    s3_client.upload_media(filename, request.FILES["file"].file.read())
    update_data[file_type] = filename

    team.branding_info = update_data
    team.save()

    response_data = {
        **team.branding_info,
        "icon_url": current_branding.brand_icon_url,
        "logo_url": current_branding.brand_logo_url,
    }
    return 200, BrandingInfoWithUrls(**response_data)

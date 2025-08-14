import uuid
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
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
from .schemas import BrandingInfo, BrandingInfoWithUrls, TeamPatchSchema, TeamResponseSchema, TeamUpdateSchema
from .utils import get_user_teams

logger = getLogger(__name__)

router = Router(tags=["Teams"], auth=(PersonalAccessTokenAuth(), django_auth))


class FieldValue(BaseModel):
    value: str | bool | None


@router.get("/{team_key}/branding", response={200: BrandingInfoWithUrls, 400: ErrorResponse, 404: ErrorResponse})
def get_team_branding(request: HttpRequest, team_key: str):
    """Get team branding information."""
    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return 404, {"detail": "Team not found"}

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
        old_filename = update_data[field]
        try:
            s3_client.delete_object(settings.AWS_MEDIA_STORAGE_BUCKET_NAME, old_filename)
        except Exception as e:
            logger.warning(f"Failed to delete old {field} file {old_filename}: {e}")
        update_data[field] = ""
    else:
        update_data[field] = data.value

    team.branding_info = update_data
    team.save()

    # Create a new BrandingInfo object with the updated data to get correct URLs
    updated_branding = BrandingInfo(**team.branding_info)
    response_data = {
        **team.branding_info,
        "icon_url": updated_branding.brand_icon_url,
        "logo_url": updated_branding.brand_logo_url,
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

    # Generate new filename first
    file_ext = Path(request.FILES["file"].name).suffix
    unique_id = str(uuid.uuid4())
    new_filename = f"team_{team.key}_{file_type}_{unique_id}{file_ext}"
    old_filename = update_data.get(file_type)

    # Upload new file first
    s3_client.upload_media(new_filename, request.FILES["file"].file.read())

    try:
        # Update database atomically
        with transaction.atomic():
            update_data[file_type] = new_filename
            team.branding_info = update_data
            team.save()

        # Only delete old file after successful database commit
        if old_filename:
            try:
                s3_client.delete_object(settings.AWS_MEDIA_STORAGE_BUCKET_NAME, old_filename)
            except Exception as e:
                logger.warning(f"Failed to delete old {file_type} file {old_filename}: {e}")

    except Exception as e:
        # Database save failed, clean up the new file we just uploaded
        try:
            s3_client.delete_object(settings.AWS_MEDIA_STORAGE_BUCKET_NAME, new_filename)
        except Exception as cleanup_error:
            logger.error(f"Failed to cleanup uploaded file {new_filename} after database error: {cleanup_error}")
        raise e

    # Create a new BrandingInfo object with the updated data to get correct URLs
    updated_branding = BrandingInfo(**team.branding_info)
    response_data = {
        **team.branding_info,
        "icon_url": updated_branding.brand_icon_url,
        "logo_url": updated_branding.brand_logo_url,
    }
    return 200, BrandingInfoWithUrls(**response_data)


@router.put(
    "/{team_key}",
    response={200: TeamResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def update_team(request: HttpRequest, team_key: str, payload: TeamUpdateSchema):
    """Update team information."""
    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return 404, {"detail": "Team not found"}

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, {"detail": "Team not found"}

    # Check if user is owner
    if not Member.objects.filter(user=request.user, team=team, role="owner").exists():
        return 403, {"detail": "Only owners can update team information"}

    try:
        with transaction.atomic():
            team.name = payload.name
            team.save()

        return 200, TeamResponseSchema(
            key=team.key,
            name=team.name,
            created_at=team.created_at.isoformat(),
            has_completed_wizard=team.has_completed_wizard,
            billing_plan=team.billing_plan,
        )

    except IntegrityError:
        return 400, {"detail": "A team with this name already exists"}
    except Exception as e:
        logger.error(f"Error updating team {team_key}: {e}")
        return 400, {"detail": "Invalid request"}


@router.patch(
    "/{team_key}",
    response={200: TeamResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def patch_team(request: HttpRequest, team_key: str, payload: TeamPatchSchema):
    """Partially update team information."""
    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return 404, {"detail": "Team not found"}

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, {"detail": "Team not found"}

    # Check if user is owner
    if not Member.objects.filter(user=request.user, team=team, role="owner").exists():
        return 403, {"detail": "Only owners can update team information"}

    try:
        with transaction.atomic():
            # Only update fields that were provided
            update_data = payload.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(team, field, value)
            team.save()

        return 200, TeamResponseSchema(
            key=team.key,
            name=team.name,
            created_at=team.created_at.isoformat(),
            has_completed_wizard=team.has_completed_wizard,
            billing_plan=team.billing_plan,
        )

    except IntegrityError:
        return 400, {"detail": "A team with this name already exists"}
    except Exception as e:
        logger.error(f"Error updating team {team_key}: {e}")
        return 400, {"detail": "Invalid request"}


@router.get("/", response={200: list[TeamResponseSchema], 403: ErrorResponse})
def list_teams(request: HttpRequest):
    """List all teams for the current user."""
    try:
        user_teams = get_user_teams(request.user)
        teams_list = []

        for team_key, team_data in user_teams.items():
            try:
                team = Team.objects.get(id=team_data["id"])
                teams_list.append(
                    TeamResponseSchema(
                        key=team.key,
                        name=team.name,
                        created_at=team.created_at.isoformat(),
                        has_completed_wizard=team.has_completed_wizard,
                        billing_plan=team.billing_plan,
                    )
                )
            except Team.DoesNotExist:
                continue

        return 200, teams_list
    except Exception as e:
        logger.error(f"Error listing teams for user {request.user.id}: {e}")
        return 403, {"detail": "Unable to retrieve teams"}


@router.get(
    "/{team_key}", response={200: TeamResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse}
)
def get_team(request: HttpRequest, team_key: str):
    """Get team information by team key."""
    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return 404, {"detail": "Team not found"}

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, {"detail": "Team not found"}

    # Check if user is a member of this team
    if not Member.objects.filter(user=request.user, team=team).exists():
        return 403, {"detail": "Access denied"}

    return 200, TeamResponseSchema(
        key=team.key,
        name=team.name,
        created_at=team.created_at.isoformat(),
        has_completed_wizard=team.has_completed_wizard,
        billing_plan=team.billing_plan,
    )

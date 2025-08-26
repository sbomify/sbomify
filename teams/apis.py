import uuid
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from ninja import File, Query, Router
from ninja.files import UploadedFile
from ninja.security import django_auth
from pydantic import BaseModel

from access_tokens.auth import PersonalAccessTokenAuth
from core.object_store import S3Client
from core.schemas import ErrorResponse
from core.utils import token_to_number
from sbomify.logging import getLogger

from .models import Member, Team
from .schemas import (
    BrandingInfo,
    BrandingInfoWithUrls,
    DependencyTrackServerCreateSchema,
    DependencyTrackServerListSchema,
    DependencyTrackServerSchema,
    PaginatedTeamsResponse,
    TeamListItemSchema,
    TeamPatchSchema,
    TeamResponseSchema,
    TeamUpdateSchema,
)
from .utils import get_user_teams

logger = getLogger(__name__)

router = Router(tags=["Workspaces"], auth=(PersonalAccessTokenAuth(), django_auth))


class FieldValue(BaseModel):
    value: str | bool | None


@router.get("/{team_key}/branding", response={200: BrandingInfoWithUrls, 400: ErrorResponse, 404: ErrorResponse})
def get_team_branding(request: HttpRequest, team_key: str):
    """Get workspace branding information.

    Note: 'team_key' parameter refers to workspace key. Teams are now called workspaces.
    """
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
    """Update a single workspace branding field.

    Note: 'team_key' parameter refers to workspace key. Teams are now called workspaces.
    """

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
    """Upload workspace branding files (icon or logo).

    Note: 'team_key' parameter refers to workspace key. Teams are now called workspaces.
    """
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
    """Update workspace information.

    Note: 'team_key' parameter refers to workspace key. Teams are now called workspaces.
    """
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
    """Partially update workspace information.

    Note: 'team_key' parameter refers to workspace key. Teams are now called workspaces.
    """
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
    """List all workspaces for the current user.

    Note: Returns workspace data. Teams are now called workspaces.
    """
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


@router.get("/dashboard", response={200: PaginatedTeamsResponse, 403: ErrorResponse})
def get_teams_dashboard_data(
    request: HttpRequest,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(15, ge=1, le=100, description="Items per page"),
    search: str = Query("", description="Search teams by name"),
):
    """Get workspace dashboard data with membership information for the current user.

    Note: Returns workspace membership data for dashboard with pagination and search. Teams are now called workspaces.
    """
    try:
        from django.db.models import Count

        # Base queryset with optimizations and annotations for statistics
        memberships_queryset = (
            Member.objects.filter(user=request.user)
            .select_related("team")
            .prefetch_related("team__member_set", "team__invitation_set")
            .annotate(
                product_count=Count("team__product", distinct=True),
                project_count=Count("team__project", distinct=True),
                component_count=Count("team__component", distinct=True),
            )
        )

        # Apply search filter
        if search.strip():
            memberships_queryset = memberships_queryset.filter(team__name__icontains=search.strip())

        # Order by default team first, then by team name
        memberships_queryset = memberships_queryset.order_by("-is_default_team", "team__name")

        # Paginate the results
        from core.apis import _paginate_queryset

        memberships, pagination_meta = _paginate_queryset(memberships_queryset, page, page_size)

        teams_list = []
        for membership in memberships:
            # Use annotated statistics (no additional queries needed)
            team = membership.team

            teams_list.append(
                TeamListItemSchema(
                    key=team.key,
                    name=team.name,
                    role=membership.role,
                    member_count=team.member_set.count(),
                    invitation_count=team.invitation_set.count(),
                    product_count=membership.product_count,
                    project_count=membership.project_count,
                    component_count=membership.component_count,
                    is_default_team=membership.is_default_team,
                    membership_id=str(membership.id),
                )
            )

        return 200, PaginatedTeamsResponse(
            items=teams_list,
            pagination=pagination_meta,
        )
    except Exception as e:
        logger.error(f"Error getting dashboard data for user {request.user.id}: {e}")
        return 403, {"detail": "Unable to retrieve dashboard data"}


@router.get(
    "/{team_key}", response={200: TeamResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse}
)
def get_team(request: HttpRequest, team_key: str):
    """Get workspace information by workspace key.

    Note: 'team_key' parameter refers to workspace key. Teams are now called workspaces.
    """
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


# DT Server Management Endpoints


@router.get(
    "/{team_key}/dt-servers", response={200: DependencyTrackServerListSchema, 403: ErrorResponse, 404: ErrorResponse}
)
def list_team_dt_servers(request: HttpRequest, team_key: str):
    """List custom DT servers for a workspace.

    Only available for Enterprise workspaces.
    """
    from vulnerability_scanning.models import DependencyTrackServer

    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return 404, {"detail": "Team not found"}

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, {"detail": "Team not found"}

    # Check if user is a member of this team
    member = Member.objects.filter(user=request.user, team=team).first()
    if not member:
        return 403, {"detail": "Access denied"}

    # Only Enterprise teams can manage custom DT servers
    if team.billing_plan != "enterprise":
        return 403, {"detail": "Custom DT servers are only available for Enterprise workspaces"}

    # Get all DT servers (for now, we'll allow Enterprise users to see all servers)
    # In the future, we might want to filter by team ownership
    servers = DependencyTrackServer.objects.all().order_by("priority", "name")

    server_data = []
    for server in servers:
        server_data.append(
            DependencyTrackServerSchema(
                id=str(server.id),
                name=server.name,
                url=server.url,
                is_active=server.is_active,
                priority=server.priority,
                max_concurrent_scans=server.max_concurrent_scans,
                current_scan_count=server.current_scan_count,
                health_status=server.health_status,
                last_health_check=server.last_health_check.isoformat() if server.last_health_check else None,
                created_at=server.created_at.isoformat(),
                updated_at=server.updated_at.isoformat(),
                api_key_set=bool(server.api_key),
            )
        )

    return 200, DependencyTrackServerListSchema(servers=server_data)


@router.post(
    "/{team_key}/dt-servers",
    response={201: DependencyTrackServerSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def create_team_dt_server(request: HttpRequest, team_key: str, data: DependencyTrackServerCreateSchema):
    """Create a new custom DT server for a workspace.

    Only available for Enterprise workspaces.
    """
    from vulnerability_scanning.models import DependencyTrackServer

    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return 404, {"detail": "Team not found"}

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, {"detail": "Team not found"}

    # Check if user is a member of this team with appropriate permissions
    member = Member.objects.filter(user=request.user, team=team).first()
    if not member:
        return 403, {"detail": "Access denied"}

    # Only owners and admins can create DT servers
    if member.role not in ["owner", "admin"]:
        return 403, {"detail": "Only workspace owners and admins can create DT servers"}

    # Only Enterprise teams can manage custom DT servers
    if team.billing_plan != "enterprise":
        return 403, {"detail": "Custom DT servers are only available for Enterprise workspaces"}

    # Validate URL uniqueness
    if DependencyTrackServer.objects.filter(url=data.url.rstrip("/")).exists():
        return 400, {"detail": "A server with this URL already exists"}

    try:
        # Create the server
        server = DependencyTrackServer.objects.create(
            name=data.name,
            url=data.url.rstrip("/"),
            api_key=data.api_key,
            priority=data.priority,
            max_concurrent_scans=data.max_concurrent_scans,
            is_active=True,
            health_status="unknown",
        )

        logger.info(f"DT server created by {request.user.email}: {server.name} ({server.id})")

        return 201, DependencyTrackServerSchema(
            id=str(server.id),
            name=server.name,
            url=server.url,
            is_active=server.is_active,
            priority=server.priority,
            max_concurrent_scans=server.max_concurrent_scans,
            current_scan_count=server.current_scan_count,
            health_status=server.health_status,
            last_health_check=server.last_health_check.isoformat() if server.last_health_check else None,
            created_at=server.created_at.isoformat(),
            updated_at=server.updated_at.isoformat(),
            api_key_set=bool(server.api_key),
        )

    except Exception as e:
        logger.error(f"Error creating DT server: {e}")
        return 400, {"detail": "Failed to create server"}


@router.delete("/{team_key}/dt-servers/{server_id}", response={204: None, 403: ErrorResponse, 404: ErrorResponse})
def delete_team_dt_server(request: HttpRequest, team_key: str, server_id: str):
    """Delete a custom DT server.

    Only available for Enterprise workspaces.
    """
    from vulnerability_scanning.models import DependencyTrackServer

    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return 404, {"detail": "Team not found"}

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, {"detail": "Team not found"}

    # Check if user is a member of this team with appropriate permissions
    member = Member.objects.filter(user=request.user, team=team).first()
    if not member:
        return 403, {"detail": "Access denied"}

    # Only owners and admins can delete DT servers
    if member.role not in ["owner", "admin"]:
        return 403, {"detail": "Only workspace owners and admins can delete DT servers"}

    # Only Enterprise teams can manage custom DT servers
    if team.billing_plan != "enterprise":
        return 403, {"detail": "Custom DT servers are only available for Enterprise workspaces"}

    try:
        server = DependencyTrackServer.objects.get(id=server_id)
    except (DependencyTrackServer.DoesNotExist, ValueError):
        return 404, {"detail": "Server not found"}

    # Check if server is currently being used
    from vulnerability_scanning.models import TeamVulnerabilitySettings

    if TeamVulnerabilitySettings.objects.filter(custom_dt_server=server).exists():
        return 400, {"detail": "Cannot delete server that is currently in use by workspaces"}

    logger.info(f"DT server deleted by {request.user.email}: {server.name} ({server.id})")
    server.delete()

    return 204, None

import uuid
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from ninja import File, Router
from ninja.files import UploadedFile
from ninja.security import django_auth
from pydantic import BaseModel

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.core.schemas import ErrorResponse
from sbomify.apps.core.utils import token_to_number
from sbomify.apps.teams.models import ContactProfile, Member, Team
from sbomify.apps.teams.schemas import (
    BrandingInfo,
    BrandingInfoWithUrls,
    ContactProfileContactSchema,
    ContactProfileCreateSchema,
    ContactProfileSchema,
    ContactProfileUpdateSchema,
    InvitationSchema,
    MemberSchema,
    TeamPatchSchema,
    TeamSchema,
    TeamUpdateSchema,
    UserSchema,
)
from sbomify.logging import getLogger

logger = getLogger(__name__)

router = Router(tags=["Workspaces"], auth=(PersonalAccessTokenAuth(), django_auth))


class FieldValue(BaseModel):
    value: str | bool | None


def _build_team_response(request: HttpRequest, team: Team) -> dict:
    current_user_id = getattr(getattr(request, "user", None), "id", None)

    members_data = [
        MemberSchema(
            id=member.id,
            user=UserSchema(
                id=member.user.id,
                first_name=member.user.first_name,
                last_name=member.user.last_name,
                email=member.user.email,
            ),
            role=member.role,
            is_default_team=member.is_default_team,
            is_me=(current_user_id == member.user.id),
        )
        for member in team.member_set.select_related("user").all()
    ]

    invitations_data = [
        InvitationSchema(
            id=invitation.id,
            email=invitation.email,
            role=invitation.role,
            created_at=invitation.created_at,
            expires_at=invitation.expires_at,
        )
        for invitation in team.invitation_set.all()
    ]

    return TeamSchema(
        key=team.key,
        name=team.name,
        created_at=team.created_at,
        billing_plan=team.billing_plan,
        billing_plan_limits=team.billing_plan_limits,
        has_completed_wizard=team.has_completed_wizard,
        members=members_data,
        invitations=invitations_data,
    )


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


def _get_team_and_membership_role(request: HttpRequest, team_key: str):
    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return None, None, (404, {"detail": "Team not found"})

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return None, None, (404, {"detail": "Team not found"})

    membership = Member.objects.filter(user=request.user, team=team).first()
    if not membership:
        return None, None, (403, {"detail": "Forbidden"})

    return team, membership.role, None


def _user_can_manage_profiles(role: str) -> bool:
    return role in {"owner", "admin"}


def _clean_url_list(urls: list[str]) -> list[str]:
    unique = []
    for url in urls:
        if url and url not in unique:
            unique.append(url)
    return unique


def _upsert_profile_contacts(profile: ContactProfile, contacts: list[ContactProfileContactSchema] | None):
    profile.contacts.all().delete()
    if not contacts:
        return

    for order, contact in enumerate(contacts):
        if not contact.name:
            continue
        profile.contacts.create(
            name=contact.name,
            email=contact.email,
            phone=contact.phone,
            order=order,
        )


def serialize_contact_profile(profile: ContactProfile) -> ContactProfileSchema:
    contacts = [
        ContactProfileContactSchema(
            name=contact.name,
            email=contact.email,
            phone=contact.phone,
            order=contact.order,
        )
        for contact in profile.contacts.all()
    ]

    return ContactProfileSchema(
        id=profile.id,
        name=profile.name,
        company=profile.company or None,
        supplier_name=profile.supplier_name or None,
        vendor=profile.vendor or None,
        email=profile.email or None,
        phone=profile.phone or None,
        address=profile.address or None,
        website_urls=_clean_url_list(profile.website_urls or []),
        contacts=contacts,
        is_default=profile.is_default,
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
    )


@router.get(
    "/{team_key}/contact-profiles",
    response={200: list[ContactProfileSchema], 403: ErrorResponse, 404: ErrorResponse},
)
def list_contact_profiles(request: HttpRequest, team_key: str):
    """List contact profiles for a workspace."""
    team, role, error = _get_team_and_membership_role(request, team_key)
    if error:
        return error

    if not _user_can_manage_profiles(role):
        return 403, {"detail": "Only owners and admins can view contact profiles"}

    profiles = ContactProfile.objects.filter(team=team).prefetch_related("contacts").order_by("-is_default", "name")
    return 200, [serialize_contact_profile(profile) for profile in profiles]


@router.post(
    "/{team_key}/contact-profiles",
    response={201: ContactProfileSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def create_contact_profile(request: HttpRequest, team_key: str, payload: ContactProfileCreateSchema):
    """Create a new contact profile for the workspace."""
    team, role, error = _get_team_and_membership_role(request, team_key)
    if error:
        return error

    if not _user_can_manage_profiles(role):
        return 403, {"detail": "Only owners and admins can manage contact profiles"}

    try:
        with transaction.atomic():
            profile = ContactProfile.objects.create(
                team=team,
                name=payload.name,
                company=payload.company or "",
                supplier_name=payload.supplier_name or "",
                vendor=payload.vendor or "",
                email=payload.email or None,
                phone=payload.phone or "",
                address=payload.address or "",
                website_urls=_clean_url_list(payload.website_urls),
                is_default=payload.is_default,
            )

            _upsert_profile_contacts(profile, payload.contacts)
            profile.refresh_from_db()

        return 201, serialize_contact_profile(profile)
    except IntegrityError:
        return 400, {"detail": "A profile with this name already exists"}


@router.patch(
    "/{team_key}/contact-profiles/{profile_id}",
    response={200: ContactProfileSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def update_contact_profile(request: HttpRequest, team_key: str, profile_id: str, payload: ContactProfileUpdateSchema):
    """Update an existing contact profile."""
    team, role, error = _get_team_and_membership_role(request, team_key)
    if error:
        return error

    if not _user_can_manage_profiles(role):
        return 403, {"detail": "Only owners and admins can manage contact profiles"}

    try:
        profile = ContactProfile.objects.get(team=team, pk=profile_id)
    except ContactProfile.DoesNotExist:
        return 404, {"detail": "Contact profile not found"}

    update_fields = {}
    for field in ["name", "company", "supplier_name", "vendor", "email", "phone", "address"]:
        value = getattr(payload, field)
        if value is not None:
            update_fields[field] = value or ""

    if payload.website_urls is not None:
        update_fields["website_urls"] = _clean_url_list(payload.website_urls)

    if payload.is_default is not None:
        update_fields["is_default"] = payload.is_default

    try:
        with transaction.atomic():
            if update_fields:
                for field, value in update_fields.items():
                    setattr(profile, field, value)
                profile.save()

            if payload.contacts is not None:
                _upsert_profile_contacts(profile, payload.contacts)

            profile.refresh_from_db()

        return 200, serialize_contact_profile(profile)
    except IntegrityError:
        return 400, {"detail": "A profile with this name already exists"}


@router.delete(
    "/{team_key}/contact-profiles/{profile_id}",
    response={204: None, 403: ErrorResponse, 404: ErrorResponse},
)
def delete_contact_profile(request: HttpRequest, team_key: str, profile_id: str):
    """Delete a workspace contact profile."""
    team, role, error = _get_team_and_membership_role(request, team_key)
    if error:
        return error

    if not _user_can_manage_profiles(role):
        return 403, {"detail": "Only owners and admins can manage contact profiles"}

    try:
        profile = ContactProfile.objects.get(team=team, pk=profile_id)
    except ContactProfile.DoesNotExist:
        return 404, {"detail": "Contact profile not found"}

    profile.delete()
    return 204, None


@router.put(
    "/{team_key}",
    response={200: TeamSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
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

        return 200, _build_team_response(request, team)

    except IntegrityError:
        return 400, {"detail": "A team with this name already exists"}
    except Exception as e:
        logger.error(f"Error updating team {team_key}: {e}")
        return 400, {"detail": "Invalid request"}


@router.patch(
    "/{team_key}",
    response={200: TeamSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
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

        return 200, _build_team_response(request, team)

    except IntegrityError:
        return 400, {"detail": "A team with this name already exists"}
    except Exception as e:
        logger.error(f"Error updating team {team_key}: {e}")
        return 400, {"detail": "Invalid request"}


@router.get("/", response={200: list[TeamSchema], 403: ErrorResponse})
def list_teams(request: HttpRequest):
    """List all workspaces for the current user.

    Note: Returns workspace data. Teams are now called workspaces.
    """
    memberships = Member.objects.filter(user=request.user).select_related("team").all()
    return 200, [_build_team_response(request, membership.team) for membership in memberships]


@router.get("/{team_key}", response={200: TeamSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse})
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

    return 200, _build_team_response(request, team)

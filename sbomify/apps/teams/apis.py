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
from sbomify.apps.teams.models import ContactEntity, ContactProfile, Member, Team
from sbomify.apps.teams.schemas import (
    BrandingInfo,
    BrandingInfoWithUrls,
    ContactEntityCreateSchema,
    ContactEntitySchema,
    ContactEntityUpdateSchema,
    ContactProfileContactSchema,
    ContactProfileCreateSchema,
    ContactProfileSchema,
    ContactProfileUpdateSchema,
    InvitationSchema,
    MemberSchema,
    TeamDomainSchema,
    TeamPatchSchema,
    TeamSchema,
    TeamUpdateSchema,
    UpdateTeamBrandingSchema,
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
            token=str(invitation.token),
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
        is_public=team.is_public,
        created_at=team.created_at,
        billing_plan=team.billing_plan,
        billing_plan_limits=team.billing_plan_limits,
        has_completed_wizard=team.has_completed_wizard,
        custom_domain=team.custom_domain,
        custom_domain_validated=team.custom_domain_validated,
        custom_domain_verification_failures=team.custom_domain_verification_failures,
        custom_domain_last_checked_at=team.custom_domain_last_checked_at,
        can_set_private=team.can_be_private(),
        members=members_data,
        invitations=invitations_data,
    )


def _private_workspace_allowed(team: Team) -> bool:
    return team.can_be_private()


def _normalize_branding_payload(branding: dict | None) -> dict:
    """Normalize branding payload and apply default colors for empty values."""
    from sbomify.apps.teams.branding import DEFAULT_ACCENT_COLOR, DEFAULT_BRAND_COLOR

    data = (branding or {}).copy()
    # Apply defaults for empty or invalid color values
    # Empty strings or legacy #000000 values should use platform defaults
    if not data.get("brand_color"):
        data["brand_color"] = DEFAULT_BRAND_COLOR
    if not data.get("accent_color"):
        data["accent_color"] = DEFAULT_ACCENT_COLOR
    return data


@router.get("/{team_key}/branding", response={200: BrandingInfoWithUrls, 400: ErrorResponse, 404: ErrorResponse})
def get_team_branding(request: HttpRequest, team_key: str):
    """Get workspace branding information.

    Note: 'team_key' parameter name is kept for backward compatibility and represents the workspace key.
    """
    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return 404, {"detail": "Workspace not found"}

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, {"detail": "Workspace not found"}

    branding_data = _normalize_branding_payload(team.branding_info)
    branding_info = BrandingInfo(**branding_data)
    response_data = {
        **branding_data,
        "icon_url": branding_info.brand_icon_url,
        "logo_url": branding_info.brand_logo_url,
    }
    return 200, BrandingInfoWithUrls(**response_data)


@router.patch(
    "/{team_key}/branding/{field}",
    response={200: BrandingInfoWithUrls, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def update_team_branding_field(
    request: HttpRequest,
    team_key: str,
    field: str,
    data: FieldValue,
):
    """Update a single workspace branding field.

    Note: 'team_key' parameter name is kept for backward compatibility and represents the workspace key.
    """

    # Validate field name
    valid_fields = {"brand_color", "accent_color", "prefer_logo_over_icon", "icon", "logo"}
    if field not in valid_fields:
        return 400, {"detail": f"Invalid field. Must be one of: {', '.join(valid_fields)}"}

    try:
        team = Team.objects.get(pk=token_to_number(team_key))
    except (ValueError, Team.DoesNotExist):
        logger.warning(f"Workspace not found: {team_key}")
        return 404, {"detail": "Workspace not found"}

    if not Member.objects.filter(user=request.user, team=team, role="owner").exists():
        logger.warning(f"User {request.user.username} is not owner of team {team_key}")
        return 403, {"detail": "Only allowed for owners"}

    branding_data = _normalize_branding_payload(team.branding_info)
    current_branding = BrandingInfo(**branding_data)
    update_data = current_branding.model_dump()

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
    updated_branding_data = _normalize_branding_payload(team.branding_info)
    updated_branding = BrandingInfo(**updated_branding_data)
    response_data = {
        **updated_branding_data,
        "icon_url": updated_branding.brand_icon_url,
        "logo_url": updated_branding.brand_logo_url,
    }
    return 200, BrandingInfoWithUrls(**response_data)


def generate_branding_filename(team: Team, field: str, file) -> str:
    file_ext = Path(file.name).suffix
    unique_id = str(uuid.uuid4())
    return f"team_{team.key}_{field}_{unique_id}{file_ext}"


def upload_to_s3(
    filename: str,
    file,
) -> None:
    s3_client = S3Client("MEDIA")
    file.seek(0)
    s3_client.upload_media(filename, file.read())


def delete_from_s3(
    filename: str,
) -> None:
    s3_client = S3Client("MEDIA")
    s3_client.delete_object(settings.AWS_MEDIA_STORAGE_BUCKET_NAME, filename)


@router.put(
    "/{team_key}/branding",
    response={200: BrandingInfoWithUrls, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def update_team_branding(
    request: HttpRequest,
    team_key: str,
    payload: UpdateTeamBrandingSchema,
):
    # TODO: has to be in middleware or decorator or anything else
    try:
        team = Team.objects.get(pk=token_to_number(team_key))
    except (ValueError, Team.DoesNotExist):
        logger.warning(f"Workspace not found: {team_key}")
        return 404, {"detail": "Workspace not found"}

    if not Member.objects.filter(user=request.user, team=team, role="owner").exists():
        logger.warning(f"User {request.user.username} is not owner of team {team_key}")
        return 403, {"detail": "Only allowed for owners"}

    # TODO: has to be a separate model
    branding_data = _normalize_branding_payload(team.branding_info)
    branding_info = BrandingInfo(**branding_data).model_dump()

    for field in ["icon", "logo"]:
        old_filename = branding_info.get(field)

        if getattr(payload, f"{field}_pending_deletion", False):
            branding_info[field] = ""
        elif file := request.FILES.get(field):
            branding_info[field] = generate_branding_filename(team, field, file)

            try:
                upload_to_s3(branding_info[field], file)
            except Exception as e:
                logger.error(f"Failed to upload {field} file {file.name}: {e}")
                raise e
        else:
            continue

        try:
            delete_from_s3(old_filename)
        except Exception as e:
            logger.warning(f"Failed to delete old {field} file {old_filename}: {e}")

    branding_info["brand_color"] = payload.brand_color or branding_info.get("brand_color")
    branding_info["accent_color"] = payload.accent_color or branding_info.get("accent_color")
    if payload.prefer_logo_over_icon is not None:
        branding_info["prefer_logo_over_icon"] = payload.prefer_logo_over_icon
    if payload.branding_enabled is not None:
        branding_info["branding_enabled"] = payload.branding_enabled

    team.branding_info = branding_info
    team.save(update_fields=["branding_info"])

    updated_branding_data = _normalize_branding_payload(team.branding_info)
    updated_branding = BrandingInfo(**updated_branding_data)
    response_data = {
        **updated_branding_data,
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

    Note: 'team_key' parameter name is kept for backward compatibility and represents the workspace key.
    """
    if file_type not in ["icon", "logo"]:
        return 400, {"detail": "Invalid file type. Must be 'icon' or 'logo'"}

    try:
        team = Team.objects.get(pk=token_to_number(team_key))
    except (ValueError, Team.DoesNotExist):
        return 404, {"detail": "Workspace not found"}

    if not Member.objects.filter(user=request.user, team=team, role="owner").exists():
        return 403, {"detail": "Only allowed for owners"}

    branding_data = _normalize_branding_payload(team.branding_info)
    current_branding = BrandingInfo(**branding_data)
    update_data = current_branding.model_dump()
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
    updated_branding_data = _normalize_branding_payload(team.branding_info)
    updated_branding = BrandingInfo(**updated_branding_data)
    response_data = {
        **updated_branding_data,
        "icon_url": updated_branding.brand_icon_url,
        "logo_url": updated_branding.brand_logo_url,
    }
    return 200, BrandingInfoWithUrls(**response_data)


def _get_team_and_membership_role(request: HttpRequest, team_key: str):
    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return None, None, (404, {"detail": "Workspace not found"})

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return None, None, (404, {"detail": "Workspace not found"})

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


def _get_team_owner_email(team: Team) -> str:
    """Get the team owner's email for fallback purposes."""
    owner = Member.objects.filter(team=team, role="owner").select_related("user").first()
    return owner.user.email if owner and owner.user and owner.user.email else "no-reply@sbomify.com"


def _upsert_entity_contacts(
    entity: ContactEntity, contacts: list[ContactProfileContactSchema] | None, fallback_email: str
):
    """Create or update contacts for an entity."""
    entity.contacts.all().delete()
    if not contacts:
        return

    for order, contact in enumerate(contacts):
        if not contact.name:
            continue
        entity.contacts.create(
            name=contact.name,
            email=contact.email or fallback_email,
            phone=contact.phone,
            order=order,
        )


def _upsert_entities(
    profile: ContactProfile,
    entities: list[ContactEntityCreateSchema | ContactEntityUpdateSchema] | None,
    fallback_email: str,
    is_update: bool = False,
):
    """Create or update entities and their contacts."""
    if entities is None:
        return

    # Collect IDs of entities that are being updated (not new ones)
    existing_ids = [e.id for e in entities if getattr(e, "id", None)]

    if is_update:
        # Safety check: Ensure we're not deleting all entities (empty list should be caught earlier)
        if len(entities) == 0:
            raise ValueError("Cannot update to zero entities - at least one entity is required")
        profile.entities.exclude(id__in=existing_ids).delete()

    for entity_data in entities:
        if not entity_data:
            continue
        entity_id = getattr(entity_data, "id", None) if is_update else None

        if entity_id:
            try:
                entity = profile.entities.get(id=entity_id)
                for field in ["name", "email", "phone", "address", "is_manufacturer", "is_supplier", "is_author"]:
                    value = getattr(entity_data, field, None)
                    if value is not None:
                        setattr(entity, field, value)
                if entity_data.website_urls is not None:
                    entity.website_urls = _clean_url_list(entity_data.website_urls)
                if not entity.email:
                    entity.email = fallback_email
                # Validate role flags before saving
                entity.full_clean()
                entity.save()
            except ContactEntity.DoesNotExist:
                continue
        else:
            # Create new entity - validation enforced by schema and model clean()
            entity = ContactEntity(
                profile=profile,
                name=entity_data.name,
                email=entity_data.email or fallback_email,
                phone=entity_data.phone or "",
                address=entity_data.address or "",
                website_urls=_clean_url_list(entity_data.website_urls or []),
                is_manufacturer=entity_data.is_manufacturer,
                is_supplier=entity_data.is_supplier,
                is_author=entity_data.is_author,
            )
            # Validate role flags before saving
            entity.full_clean()
            entity.save()

        contacts = getattr(entity_data, "contacts", None)
        if contacts is not None:
            _upsert_entity_contacts(entity, contacts, fallback_email)


def serialize_contact_profile(profile: ContactProfile) -> ContactProfileSchema:
    """Serialize a contact profile with entities and legacy fields for backward compatibility."""
    entities = []
    for entity in profile.entities.all():
        entity_contacts = [
            ContactProfileContactSchema(
                name=c.name,
                email=c.email,
                phone=c.phone,
                order=c.order,
            )
            for c in entity.contacts.all()
        ]
        entities.append(
            ContactEntitySchema(
                id=entity.id,
                name=entity.name,
                email=entity.email,
                phone=entity.phone or None,
                address=entity.address or None,
                website_urls=_clean_url_list(entity.website_urls or []),
                is_manufacturer=entity.is_manufacturer,
                is_supplier=entity.is_supplier,
                is_author=entity.is_author,
                contacts=entity_contacts,
                created_at=entity.created_at.isoformat(),
                updated_at=entity.updated_at.isoformat(),
            )
        )

    first_entity = profile.entities.first()
    legacy_contacts = []
    if first_entity:
        legacy_contacts = [
            ContactProfileContactSchema(
                name=c.name,
                email=c.email,
                phone=c.phone,
                order=c.order,
            )
            for c in first_entity.contacts.all()
        ]

    return ContactProfileSchema(
        id=profile.id,
        name=profile.name,
        entities=entities,
        company=first_entity.name if first_entity else None,
        supplier_name=first_entity.name if first_entity else None,
        vendor=first_entity.name if first_entity else None,
        email=first_entity.email if first_entity else None,
        phone=first_entity.phone if first_entity else None,
        address=first_entity.address if first_entity else None,
        website_urls=_clean_url_list(first_entity.website_urls or []) if first_entity else [],
        contacts=legacy_contacts,
        is_default=profile.is_default,
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
    )


@router.get(
    "/{team_key}/contact-profiles",
    response={200: list[ContactProfileSchema], 403: ErrorResponse, 404: ErrorResponse},
)
def list_contact_profiles(request: HttpRequest, team_key: str):
    """List contact profiles for a workspace.

    All team members can view contact profiles, but only owners and admins can manage them.
    """
    team, role, error = _get_team_and_membership_role(request, team_key)
    if error:
        return error

    # Allow all team members to view contact profiles (for use in component metadata)
    profiles = (
        ContactProfile.objects.filter(team=team)
        .prefetch_related("entities", "entities__contacts")
        .order_by("-is_default", "name")
    )
    return 200, [serialize_contact_profile(profile) for profile in profiles]


@router.get(
    "/{team_key}/contact-profiles/{profile_id}",
    response={200: ContactProfileSchema, 403: ErrorResponse, 404: ErrorResponse},
)
def get_contact_profile(request: HttpRequest, team_key: str, profile_id: str, return_instance: bool = False):
    """Get a specific contact profile.

    All team members can view contact profiles, but only owners and admins can manage them.
    """
    team, role, error = _get_team_and_membership_role(request, team_key)
    if error:
        return error

    # Allow all team members to view contact profiles (for use in component metadata)
    try:
        profile = ContactProfile.objects.prefetch_related("entities", "entities__contacts").get(
            team=team, pk=profile_id
        )
    except ContactProfile.DoesNotExist:
        return 404, {"detail": "Contact profile not found"}

    response = profile if return_instance else serialize_contact_profile(profile)
    return 200, response


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
                is_default=payload.is_default,
            )

            fallback_email = _get_team_owner_email(team)

            # Handle entity-based structure (new API)
            if payload.entities is not None:
                if not payload.entities:
                    return 400, {"detail": "At least one entity is required"}
                _upsert_entities(profile, payload.entities, fallback_email)
            elif any(
                [
                    payload.company,
                    payload.supplier_name,
                    payload.vendor,
                    payload.email,
                    payload.phone,
                    payload.address,
                    payload.website_urls is not None,
                    payload.contacts is not None,
                ]
            ):
                # Handle legacy flat fields (backward compatibility)
                entity_name = payload.company or payload.supplier_name or payload.vendor or "Default Entity"
                entity_email = payload.email or fallback_email
                entity = profile.entities.create(
                    name=entity_name,
                    email=entity_email,
                    phone=payload.phone or "",
                    address=payload.address or "",
                    website_urls=_clean_url_list(payload.website_urls or []),
                    is_manufacturer=True,
                    is_supplier=True,
                    is_author=True,
                )
                if payload.contacts:
                    _upsert_entity_contacts(entity, payload.contacts, fallback_email)
            else:
                # No entities provided and no legacy fields - require at least one entity
                return 400, {"detail": "At least one entity is required. Provide 'entities' array or legacy fields."}

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
        profile = ContactProfile.objects.prefetch_related("entities", "entities__contacts").get(
            team=team, pk=profile_id
        )
    except ContactProfile.DoesNotExist:
        return 404, {"detail": "Contact profile not found"}

    try:
        with transaction.atomic():
            # Update profile name if provided
            if payload.name is not None:
                profile.name = payload.name
            if payload.is_default is not None:
                profile.is_default = payload.is_default
            profile.save()

            fallback_email = _get_team_owner_email(team)

            # Handle entity-based structure (new API)
            if payload.entities is not None:
                if not payload.entities:
                    return 400, {"detail": "At least one entity is required"}
                _upsert_entities(profile, payload.entities, fallback_email, is_update=True)
            # Handle legacy flat fields (backward compatibility)
            elif any(
                [
                    payload.company,
                    payload.supplier_name,
                    payload.vendor,
                    payload.email,
                    payload.phone,
                    payload.address,
                    payload.website_urls is not None,
                    payload.contacts is not None,
                ]
            ):
                first_entity = profile.entities.first()
                if first_entity:
                    if payload.company is not None:
                        first_entity.name = payload.company or first_entity.name
                    if payload.email is not None:
                        first_entity.email = payload.email or fallback_email
                    if payload.phone is not None:
                        first_entity.phone = payload.phone
                    if payload.address is not None:
                        first_entity.address = payload.address
                    if payload.website_urls is not None:
                        first_entity.website_urls = _clean_url_list(payload.website_urls)
                    # Force all roles True for backward compatibility when using legacy fields
                    first_entity.is_manufacturer = True
                    first_entity.is_supplier = True
                    first_entity.is_author = True
                    first_entity.full_clean()
                    first_entity.save()

                    if payload.contacts is not None:
                        _upsert_entity_contacts(first_entity, payload.contacts, fallback_email)
                else:
                    # No entity exists, create one from legacy fields
                    entity_name = payload.company or payload.supplier_name or payload.vendor or "Default Entity"
                    entity_email = payload.email or fallback_email
                    entity = profile.entities.create(
                        name=entity_name,
                        email=entity_email,
                        phone=payload.phone or "",
                        address=payload.address or "",
                        website_urls=_clean_url_list(payload.website_urls or []),
                        is_manufacturer=True,
                        is_supplier=True,
                        is_author=True,
                    )
                    if payload.contacts:
                        _upsert_entity_contacts(entity, payload.contacts, fallback_email)

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

    Note: 'team_key' parameter name is kept for backward compatibility and represents the workspace key.
    """
    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return 404, {"detail": "Workspace not found"}

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, {"detail": "Workspace not found"}

    # Check if user is owner
    if not Member.objects.filter(user=request.user, team=team, role="owner").exists():
        return 403, {"detail": "Only owners can update team information"}

    try:
        with transaction.atomic():
            team.name = payload.name
            if payload.is_public is not None:
                if payload.is_public is False and not _private_workspace_allowed(team):
                    return 403, {"detail": "Disabling the Trust Center is available on Business or Enterprise plans."}
                team.is_public = payload.is_public
            team.save()

        return 200, _build_team_response(request, team)

    except IntegrityError:
        return 400, {"detail": "A team with this name already exists"}
    except ValueError as exc:
        logger.warning(f"Invalid billing plan for team {team_key}: {exc}")
        return 400, {"detail": str(exc)}
    except Exception as e:
        logger.error(f"Error updating team {team_key}: {e}")
        return 400, {"detail": "Invalid request"}


@router.patch(
    "/{team_key}",
    response={200: TeamSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def patch_team(request: HttpRequest, team_key: str, payload: TeamPatchSchema):
    """Partially update workspace information.

    Note: 'team_key' parameter name is retained for backward compatibility and represents the workspace key.
    """
    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return 404, {"detail": "Workspace not found"}

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, {"detail": "Workspace not found"}

    # Check if user is owner
    if not Member.objects.filter(user=request.user, team=team, role="owner").exists():
        return 403, {"detail": "Only owners can update team information"}

    try:
        with transaction.atomic():
            # Only update fields that were provided
            update_data = payload.model_dump(exclude_unset=True)
            desired_visibility = update_data.get("is_public")
            if desired_visibility is False and not _private_workspace_allowed(team):
                return 403, {"detail": "Disabling the Trust Center is available on Business or Enterprise plans."}
            for field, value in update_data.items():
                setattr(team, field, value)
            team.save()

        return 200, _build_team_response(request, team)

    except IntegrityError:
        return 400, {"detail": "A team with this name already exists"}
    except ValueError as exc:
        logger.warning(f"Invalid billing plan for team {team_key}: {exc}")
        return 400, {"detail": str(exc)}
    except Exception as e:
        logger.error(f"Error updating team {team_key}: {e}")
        return 400, {"detail": "Invalid request"}


class TeamDomainResponseSchema(BaseModel):
    domain: str
    validated: bool


@router.put(
    "/{team_key}/domain",
    response={200: TeamDomainResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
@router.patch(
    "/{team_key}/domain",
    response={200: TeamDomainResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def update_team_domain(request: HttpRequest, team_key: str, payload: TeamDomainSchema):
    """Set or update workspace custom domain."""
    from sbomify.apps.teams.utils import invalidate_custom_domain_cache
    from sbomify.apps.teams.validators import validate_custom_domain

    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return 404, {"detail": "Workspace not found"}

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, {"detail": "Workspace not found"}

    # Check if user is owner
    if not Member.objects.filter(user=request.user, team=team, role="owner").exists():
        return 403, {"detail": "Only owners can update team domain"}

    # Feature gating: Check billing plan
    from sbomify.apps.billing.models import BillingPlan

    plan_key = team.billing_plan or "free"
    try:
        plan = BillingPlan.objects.get(key=plan_key)
        has_access = plan.has_custom_domain_access
    except BillingPlan.DoesNotExist:
        # Fallback for unknown plans
        has_access = plan_key in ["business", "enterprise"]

    if not has_access:
        return 403, {"detail": "Custom domains are available on Business and Enterprise plans only"}

    # Validate domain format using comprehensive FQDN validation
    is_valid, error_message = validate_custom_domain(payload.domain)
    if not is_valid:
        return 400, {"detail": error_message}

    # Store old domain for cache invalidation
    old_domain = team.custom_domain

    try:
        # Normalize domain (validator already does this, but be explicit)
        normalized_domain = payload.domain.strip().lower()

        with transaction.atomic():
            team.custom_domain = normalized_domain
            team.custom_domain_validated = False  # Reset validation on change
            team.save(update_fields=["custom_domain", "custom_domain_validated"])

        # Invalidate cache for both old and new domains
        invalidate_custom_domain_cache(old_domain)
        invalidate_custom_domain_cache(normalized_domain)

        return 200, {"domain": team.custom_domain, "validated": team.custom_domain_validated}

    except IntegrityError:
        return 400, {"detail": "This domain is already in use by another workspace"}
    except Exception as e:
        logger.error(f"Error updating team domain {team_key}: {e}")
        return 400, {"detail": "Invalid request"}


@router.delete(
    "/{team_key}/domain",
    response={204: None, 403: ErrorResponse, 404: ErrorResponse},
)
def delete_team_domain(request: HttpRequest, team_key: str):
    """Remove workspace custom domain."""
    from sbomify.apps.teams.utils import invalidate_custom_domain_cache

    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return 404, {"detail": "Workspace not found"}

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, {"detail": "Workspace not found"}

    # Check if user is owner
    if not Member.objects.filter(user=request.user, team=team, role="owner").exists():
        return 403, {"detail": "Only owners can update team domain"}

    # Store domain for cache invalidation
    old_domain = team.custom_domain

    team.custom_domain = None
    team.custom_domain_validated = False
    team.save(update_fields=["custom_domain", "custom_domain_validated"])

    # Invalidate cache for removed domain
    invalidate_custom_domain_cache(old_domain)

    return 204, None


@router.get("/", response={200: list[TeamSchema], 403: ErrorResponse})
def list_teams(request: HttpRequest):
    """List all workspaces for the current user.

    Note: Returns workspace data. Internal identifiers retain legacy naming for compatibility.
    """
    memberships = (
        Member.objects.filter(user=request.user).select_related("team").order_by("team__created_at", "team__id").all()
    )
    return 200, [_build_team_response(request, membership.team) for membership in memberships]


@router.get("/{team_key}", response={200: TeamSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse})
def get_team(request: HttpRequest, team_key: str):
    """Get workspace information by workspace key.

    Note: 'team_key' parameter name is kept for backward compatibility and represents the workspace key.
    """
    try:
        team_id = token_to_number(team_key)
    except ValueError:
        return 404, {"detail": "Workspace not found"}

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, {"detail": "Workspace not found"}

    # Check if user is a member of this team
    if not Member.objects.filter(user=request.user, team=team).exists():
        return 403, {"detail": "Access denied"}

    return 200, _build_team_response(request, team)


# Internal endpoints (no auth required - secured at proxy level)
internal_router = Router(tags=["Internal"], auth=None)


@internal_router.get("/domains", response={200: None, 404: None})
def check_domain_allowed(request: HttpRequest, domain: str):
    """
    Check if a domain is allowed for on-demand TLS certificate provisioning.

    This endpoint is used by Caddy's on-demand TLS feature. Caddy will call this
    endpoint with ?domain=example.com before issuing a certificate.

    Expected behavior (per Caddy docs):
    - Return 200 OK if the domain is recognized and should get a certificate
    - Return 404 (or any non-200) if the domain should NOT get a certificate

    Allowed domains:
    - Main application domain (APP_BASE_URL)
    - Custom domains from teams with Business or Enterprise plans

    Security: This endpoint MUST be blocked from external access at the proxy level.
    See Caddyfile configuration for access restrictions.

    Args:
        domain: The domain name to check (provided as query parameter by Caddy)

    Returns:
        200 OK if domain is allowed, 404 if not allowed
    """
    from urllib.parse import urlparse

    logger.info(f"On-demand TLS check: domain={domain} from {request.META.get('REMOTE_ADDR')}")

    # Sanitize and normalize domain input using urlparse
    # This handles cases where input might include protocol, port, or path
    # Note: urlparse requires a scheme to identify hostname, so we add one if missing
    domain_input = domain.strip()
    if not domain_input.startswith(("http://", "https://")):
        domain_input = f"http://{domain_input}"

    try:
        parsed = urlparse(domain_input)
        # Extract just the hostname (strips port, path, query, etc.)
        domain_normalized = parsed.hostname
        if not domain_normalized:
            logger.warning(f"On-demand TLS denied: invalid domain format (no hostname extracted): {domain}")
            return 404, None
        domain_normalized = domain_normalized.lower()
    except (ValueError, AttributeError) as e:
        # Invalid domain format
        logger.warning(f"On-demand TLS denied: failed to parse domain '{domain}': {e}")
        return 404, None

    # Check if domain is the main application domain
    if settings.APP_BASE_URL:
        try:
            app_base_url_input = settings.APP_BASE_URL.strip()
            if not app_base_url_input.startswith(("http://", "https://")):
                app_base_url_input = f"http://{app_base_url_input}"
            parsed_app = urlparse(app_base_url_input)
            app_domain = parsed_app.hostname
            if app_domain and domain_normalized == app_domain.lower():
                logger.info(f"On-demand TLS approved: {domain_normalized} (main application domain)")
                return 200, None
        except (ValueError, AttributeError):
            # Invalid APP_BASE_URL - continue to check custom domains
            logger.warning(f"Failed to parse APP_BASE_URL: {settings.APP_BASE_URL}")
            pass

    # Check if domain exists and belongs to Business/Enterprise team
    is_allowed = Team.objects.filter(
        custom_domain=domain_normalized, billing_plan__in=["business", "enterprise"]
    ).exists()

    if is_allowed:
        logger.info(f"On-demand TLS approved: {domain_normalized} (custom domain)")
        return 200, None
    else:
        logger.warning(f"On-demand TLS denied: {domain_normalized} (not found in allowed domains)")
        return 404, None

import tempfile
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from ninja import Query, Router
from ninja.decorators import decorate_view
from ninja.security import django_auth
from pydantic import BaseModel, ValidationError

from access_tokens.auth import PersonalAccessTokenAuth, optional_auth, optional_token_auth
from billing.config import is_billing_enabled
from billing.models import BillingPlan
from core.object_store import S3Client
from core.schemas import ItemTypes
from core.utils import verify_item_access
from sbomify.logging import getLogger
from sboms.schemas import (
    ComponentMetaData,
    ComponentMetaDataPatch,
)
from sboms.utils import get_product_sbom_package, get_project_sbom_package, get_release_sbom_package
from teams.models import Team
from teams.utils import get_user_teams

from .models import Component, Product, Project, Release, ReleaseArtifact
from .schemas import (
    ComponentCreateSchema,
    ComponentPatchSchema,
    ComponentResponseSchema,
    ComponentUpdateSchema,
    DashboardSBOMUploadInfo,
    DashboardStatsResponse,
    DocumentReleaseTaggingResponseSchema,
    DocumentReleaseTaggingSchema,
    ErrorCode,
    ErrorResponse,
    ProductCreateSchema,
    ProductIdentifierBulkUpdateSchema,
    ProductIdentifierCreateSchema,
    ProductIdentifierSchema,
    ProductIdentifierUpdateSchema,
    ProductLinkBulkUpdateSchema,
    ProductLinkCreateSchema,
    ProductLinkSchema,
    ProductLinkUpdateSchema,
    ProductPatchSchema,
    ProductResponseSchema,
    ProductUpdateSchema,
    ProjectCreateSchema,
    ProjectPatchSchema,
    ProjectResponseSchema,
    ProjectUpdateSchema,
    ReleaseArtifactAddResponseSchema,
    ReleaseArtifactCreateSchema,
    ReleaseCreateSchema,
    ReleasePatchSchema,
    ReleaseResponseSchema,
    ReleaseUpdateSchema,
    SBOMReleaseTaggingResponseSchema,
    SBOMReleaseTaggingSchema,
    UserItemsResponse,
)

log = getLogger(__name__)


# Creation schemas
class CreateItemRequest(BaseModel):
    name: str


class CreateItemResponse(BaseModel):
    id: str


class CreateProjectRequest(BaseModel):
    name: str
    product_id: str


router = Router(tags=["Core"], auth=(PersonalAccessTokenAuth(), django_auth))

item_type_map = {"team": Team, "component": Component, "project": Project, "product": Product}


def _get_user_team_id(request: HttpRequest) -> str | None:
    """Get the current user's team ID from the session or fall back to user's first team."""
    from core.utils import get_team_id_from_session
    from teams.models import Team

    # First try session-based team (for web UI)
    team_id = get_team_id_from_session(request)
    if team_id:
        return team_id

    # Fall back to user's first team (for API calls with bearer tokens)
    if request.user and request.user.is_authenticated:
        first_team = Team.objects.filter(member__user=request.user).first()
        if first_team:
            return str(first_team.id)

    return None


def _ensure_latest_release_exists(product: "Product") -> None:
    """Ensure a latest release exists for the product.

    This function is called when users access products to proactively create
    latest releases if they don't exist. Failures are logged but don't
    interrupt the main request flow.

    Args:
        product: The product to ensure has a latest release
    """
    try:
        # Import here to avoid circular imports
        from core.models import Release

        # This will create the latest release if it doesn't exist
        Release.get_or_create_latest_release(product)

    except Exception as e:
        # Log the error but don't fail the main request
        log.warning(f"Failed to ensure latest release for product {product.id}: {e}")


def _build_item_response(item, item_type: str):
    """Build a standardized response for items."""
    base_response = {
        "id": item.id,
        "name": item.name,
        "team_id": str(item.team_id),
        "is_public": item.is_public,
        "created_at": item.created_at.isoformat(),
    }

    if item_type == "product":
        base_response["project_count"] = item.projects.count()
        # Include actual projects data for frontend
        base_response["projects"] = [
            {
                "id": project.id,
                "name": project.name,
                "is_public": project.is_public,
            }
            for project in item.projects.all()
        ]
        # Include identifiers data
        base_response["identifiers"] = [
            {
                "id": identifier.id,
                "identifier_type": identifier.identifier_type,
                "value": identifier.value,
                "created_at": identifier.created_at.isoformat(),
            }
            for identifier in item.identifiers.all()
        ]
        # Include links data
        base_response["links"] = [
            {
                "id": link.id,
                "link_type": link.link_type,
                "title": link.title,
                "url": link.url,
                "description": link.description,
                "created_at": link.created_at.isoformat(),
            }
            for link in item.links.all()
        ]
    elif item_type == "project":
        base_response["component_count"] = item.components.count()
        base_response["metadata"] = item.metadata
        # Include actual components data for frontend
        base_response["components"] = [
            {
                "id": component.id,
                "name": component.name,
                "is_public": component.is_public,
                "component_type": component.component_type,
            }
            for component in item.components.all()
        ]
    elif item_type == "component":
        base_response["sbom_count"] = item.sbom_set.count()
        base_response["metadata"] = item.metadata
        base_response["component_type"] = item.component_type

    return base_response


@router.get(
    "/user-items/{item_type}",
    response={
        200: list[UserItemsResponse],
        400: ErrorResponse,
    },
)
def get_user_items(request, item_type: ItemTypes) -> list[UserItemsResponse]:
    "Get all items of a specific type (across all teams) that belong to the current user."
    user_teams = get_user_teams(user=request.user)
    Model = item_type_map[item_type]

    result = []
    team_id_to_key = {v["id"]: k for k, v in user_teams.items() if "id" in v}
    item_records = Model.objects.filter(team_id__in=team_id_to_key.keys())

    for item in item_records:
        team_key = team_id_to_key[item.team_id]
        result.append(
            UserItemsResponse(
                team_key=team_key,
                team_name=user_teams[team_key]["name"],
                item_key=item.id,
                item_name=item.name,
            )
        )

    return result


def _check_billing_limits(team_id: str, resource_type: str) -> tuple[bool, str, ErrorCode | None]:
    """
    Check if team has reached billing limits for the given resource type.

    Returns:
        (can_create, error_message, error_code): Tuple of boolean, error message, and error code
    """
    if not is_billing_enabled():
        return True, "", None

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return False, "Team not found", ErrorCode.TEAM_NOT_FOUND

    if not team.billing_plan:
        return False, "No active billing plan", ErrorCode.NO_BILLING_PLAN

    try:
        plan = BillingPlan.objects.get(key=team.billing_plan)
    except BillingPlan.DoesNotExist:
        return False, "Invalid billing plan", ErrorCode.INVALID_BILLING_PLAN

    # Get current count and limits
    if resource_type == "product":
        current_count = Product.objects.filter(team_id=team_id).count()
        max_allowed = plan.max_products
    elif resource_type == "project":
        current_count = Project.objects.filter(team_id=team_id).count()
        max_allowed = plan.max_projects
    elif resource_type == "component":
        current_count = Component.objects.filter(team_id=team_id).count()
        max_allowed = plan.max_components
    else:
        return False, f"Invalid resource type: {resource_type}", ErrorCode.INVALID_DATA

    # Enterprise plan or None (unlimited) values have no limits
    if plan.key == "enterprise" or max_allowed is None:
        return True, "", None

    # Check if limit is reached
    if current_count >= max_allowed:
        return (
            False,
            f"You have reached the maximum {max_allowed} {resource_type}s allowed by your plan",
            ErrorCode.BILLING_LIMIT_EXCEEDED,
        )

    return True, "", None


# =============================================================================
# PRODUCT CRUD ENDPOINTS
# =============================================================================


@router.post(
    "/products",
    response={201: ProductResponseSchema, 400: ErrorResponse, 403: ErrorResponse},
)
def create_product(request: HttpRequest, payload: ProductCreateSchema):
    """Create a new product."""
    team_id = _get_user_team_id(request)
    if not team_id:
        return 403, {"detail": "No current team selected", "error_code": ErrorCode.NO_CURRENT_TEAM}

    # Check billing limits
    can_create, error_msg, error_code = _check_billing_limits(team_id, "product")
    if not can_create:
        return 403, {"detail": error_msg, "error_code": error_code}

    try:
        # Check if user has permission to create products in this team
        team = Team.objects.get(id=team_id)
        if not verify_item_access(request, team, ["owner", "admin"]):
            return 403, {"detail": "Only owners and admins can create products", "error_code": ErrorCode.FORBIDDEN}

        with transaction.atomic():
            product = Product.objects.create(
                name=payload.name,
                team_id=team_id,
            )

        return 201, _build_item_response(product, "product")

    except IntegrityError:
        return 400, {
            "detail": "A product with this name already exists in this team",
            "error_code": ErrorCode.DUPLICATE_NAME,
        }
    except Team.DoesNotExist:
        return 403, {"detail": "Team not found", "error_code": ErrorCode.TEAM_NOT_FOUND}
    except Exception as e:
        log.error(f"Error creating product: {e}")
        return 400, {"detail": str(e), "error_code": ErrorCode.INTERNAL_ERROR}


@router.get(
    "/products",
    response={200: list[ProductResponseSchema], 403: ErrorResponse},
)
def list_products(request: HttpRequest):
    """List all products for the current user's team."""
    team_id = _get_user_team_id(request)
    if not team_id:
        return 403, {"detail": "No current team selected"}

    try:
        products = Product.objects.filter(team_id=team_id).prefetch_related("projects", "identifiers", "links")

        # Ensure latest releases exist for all products when users view their dashboard
        for product in products:
            _ensure_latest_release_exists(product)

        return 200, [_build_item_response(product, "product") for product in products]
    except Exception as e:
        log.error(f"Error listing products: {e}")
        return 400, {"detail": str(e)}


@router.get(
    "/products/{product_id}",
    response={200: ProductResponseSchema, 403: ErrorResponse, 404: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def get_product(request: HttpRequest, product_id: str):
    """Get a specific product by ID."""
    try:
        product = Product.objects.prefetch_related("projects", "identifiers", "links").get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    # Ensure latest release exists when users access the product
    _ensure_latest_release_exists(product)

    # If product is public, allow unauthenticated access
    if product.is_public:
        return 200, _build_item_response(product, "product")

    # For private products, require authentication and team access
    if not request.user or not request.user.is_authenticated:
        return 403, {"detail": "Authentication required for private items"}

    if not verify_item_access(request, product, ["guest", "owner", "admin"]):
        return 403, {"detail": "Forbidden"}

    return 200, _build_item_response(product, "product")


@router.put(
    "/products/{product_id}",
    response={200: ProductResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def update_product(request: HttpRequest, product_id: str, payload: ProductUpdateSchema):
    """Update a product."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can update products"}

    try:
        with transaction.atomic():
            product.name = payload.name
            product.is_public = payload.is_public
            product.save()

        return 200, _build_item_response(product, "product")

    except IntegrityError:
        return 400, {"detail": "A product with this name already exists in this team"}
    except Exception as e:
        log.error(f"Error updating product {product_id}: {e}")
        return 400, {"detail": str(e)}


@router.patch(
    "/products/{product_id}",
    response={200: ProductResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def patch_product(request: HttpRequest, product_id: str, payload: ProductPatchSchema):
    """Partially update a product."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can update products"}

    try:
        with transaction.atomic():
            # Handle relationship updates separately
            update_data = payload.model_dump(exclude_unset=True)
            project_ids = update_data.pop("project_ids", None)

            # Validate public/private constraints before making changes
            new_is_public = update_data.get("is_public", product.is_public)

            # Check billing plan restrictions when trying to make items private
            if not new_is_public and product.is_public:
                # Get the team from the product
                team = product.team

                # Only enforce billing restrictions if billing is enabled
                if is_billing_enabled() and team.billing_plan == "community":
                    return 403, {
                        "detail": (
                            "Community plan users cannot make items private. "
                            "Upgrade to a paid plan to enable private items."
                        )
                    }

            # If making product public, check if it has private projects
            if new_is_public and not product.is_public:
                private_projects = product.projects.filter(is_public=False)
                if private_projects.exists():
                    project_names = ", ".join(private_projects.values_list("name", flat=True))
                    return 400, {
                        "detail": (
                            f"Cannot make product public because it contains private projects: {project_names}. "
                            "Please make all projects public first."
                        )
                    }

            # If updating project relationships, validate constraints
            if project_ids is not None:
                # Verify all projects exist and belong to the same team
                projects = Project.objects.filter(id__in=project_ids, team_id=product.team_id)
                if len(projects) != len(project_ids):
                    return 400, {"detail": "Some projects were not found or don't belong to this team"}

                # Verify access to all projects
                for project in projects:
                    if not verify_item_access(request, project, ["owner", "admin"]):
                        return 403, {"detail": f"No permission to modify project {project.name}"}

                # If product is (or will be) public, ensure no private projects are being assigned
                if new_is_public:
                    private_projects = [p for p in projects if not p.is_public]
                    if private_projects:
                        project_names = ", ".join([p.name for p in private_projects])
                        return 400, {
                            "detail": (
                                f"Cannot assign private projects to a public product: {project_names}. "
                                "Please make these projects public first or keep the product private."
                            )
                        }

                # Update relationships
                product.projects.set(projects)

            # Update simple fields
            for field, value in update_data.items():
                setattr(product, field, value)
            product.save()

        return 200, _build_item_response(product, "product")

    except IntegrityError:
        return 400, {"detail": "A product with this name already exists in this team"}
    except Exception as e:
        log.error(f"Error patching product {product_id}: {e}")
        return 400, {"detail": str(e)}


@router.delete(
    "/products/{product_id}",
    response={204: None, 403: ErrorResponse, 404: ErrorResponse},
)
def delete_product(request: HttpRequest, product_id: str):
    """Delete a product."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can delete products"}

    try:
        product.delete()
        return 204, None
    except Exception as e:
        log.error(f"Error deleting product {product_id}: {e}")
        return 400, {"detail": str(e)}


# =============================================================================
# PRODUCT IDENTIFIER CRUD ENDPOINTS
# =============================================================================


@router.post(
    "/products/{product_id}/identifiers",
    response={201: ProductIdentifierSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def create_product_identifier(request: HttpRequest, product_id: str, payload: ProductIdentifierCreateSchema):
    """Create a new product identifier."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can manage product identifiers"}

    # Check billing plan restrictions - product identifiers only for business and enterprise
    if is_billing_enabled() and product.team.billing_plan == "community":
        return 403, {
            "detail": (
                "Product identifiers are only available for business and enterprise plans. "
                "Upgrade your plan to access this feature."
            ),
            "error_code": ErrorCode.BILLING_LIMIT_EXCEEDED,
        }

    try:
        with transaction.atomic():
            # Import here to avoid issues
            from sboms.models import ProductIdentifier

            identifier = ProductIdentifier.objects.create(
                product=product,
                identifier_type=payload.identifier_type,
                value=payload.value,
            )

        return 201, {
            "id": identifier.id,
            "identifier_type": identifier.identifier_type,
            "value": identifier.value,
            "created_at": identifier.created_at.isoformat(),
        }

    except IntegrityError:
        return 400, {
            "detail": (
                f"An identifier of type {payload.identifier_type} "
                f"with value '{payload.value}' already exists in this team"
            ),
            "error_code": ErrorCode.DUPLICATE_NAME,
        }
    except Exception as e:
        log.error(f"Error creating product identifier: {e}")
        return 400, {"detail": str(e), "error_code": ErrorCode.INTERNAL_ERROR}


@router.get(
    "/products/{product_id}/identifiers",
    response={200: list[ProductIdentifierSchema], 403: ErrorResponse, 404: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def list_product_identifiers(request: HttpRequest, product_id: str):
    """List all identifiers for a product."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    # If product is public, allow unauthenticated access
    if product.is_public:
        pass
    else:
        # For private products, require authentication and team access
        if not request.user or not request.user.is_authenticated:
            return 403, {"detail": "Authentication required for private items"}

        if not verify_item_access(request, product, ["guest", "owner", "admin"]):
            return 403, {"detail": "Forbidden"}

    try:
        identifiers = product.identifiers.all()
        return 200, [
            {
                "id": identifier.id,
                "identifier_type": identifier.identifier_type,
                "value": identifier.value,
                "created_at": identifier.created_at.isoformat(),
            }
            for identifier in identifiers
        ]
    except Exception as e:
        log.error(f"Error listing product identifiers: {e}")
        return 400, {"detail": str(e)}


@router.put(
    "/products/{product_id}/identifiers/{identifier_id}",
    response={200: ProductIdentifierSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def update_product_identifier(
    request: HttpRequest, product_id: str, identifier_id: str, payload: ProductIdentifierUpdateSchema
):
    """Update a product identifier."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can manage product identifiers"}

    # Check billing plan restrictions - product identifiers only for business and enterprise
    if is_billing_enabled() and product.team.billing_plan == "community":
        return 403, {
            "detail": (
                "Product identifiers are only available for business and enterprise plans. "
                "Upgrade your plan to access this feature."
            ),
            "error_code": ErrorCode.BILLING_LIMIT_EXCEEDED,
        }

    try:
        # Import here to avoid issues
        from sboms.models import ProductIdentifier

        identifier = ProductIdentifier.objects.get(pk=identifier_id, product=product)
    except ProductIdentifier.DoesNotExist:
        return 404, {"detail": "Product identifier not found"}

    try:
        with transaction.atomic():
            identifier.identifier_type = payload.identifier_type
            identifier.value = payload.value
            identifier.save()

        return 200, {
            "id": identifier.id,
            "identifier_type": identifier.identifier_type,
            "value": identifier.value,
            "created_at": identifier.created_at.isoformat(),
        }

    except IntegrityError:
        return 400, {
            "detail": (
                f"An identifier of type {payload.identifier_type} "
                f"with value '{payload.value}' already exists in this team"
            )
        }
    except Exception as e:
        log.error(f"Error updating product identifier {identifier_id}: {e}")
        return 400, {"detail": str(e)}


@router.delete(
    "/products/{product_id}/identifiers/{identifier_id}",
    response={204: None, 403: ErrorResponse, 404: ErrorResponse},
)
def delete_product_identifier(request: HttpRequest, product_id: str, identifier_id: str):
    """Delete a product identifier."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can manage product identifiers"}

    # Check billing plan restrictions - product identifiers only for business and enterprise
    if is_billing_enabled() and product.team.billing_plan == "community":
        return 403, {
            "detail": (
                "Product identifiers are only available for business and enterprise plans. "
                "Upgrade your plan to access this feature."
            ),
            "error_code": ErrorCode.BILLING_LIMIT_EXCEEDED,
        }

    try:
        # Import here to avoid issues
        from sboms.models import ProductIdentifier

        identifier = ProductIdentifier.objects.get(pk=identifier_id, product=product)
    except ProductIdentifier.DoesNotExist:
        return 404, {"detail": "Product identifier not found"}

    try:
        identifier.delete()
        return 204, None
    except Exception as e:
        log.error(f"Error deleting product identifier {identifier_id}: {e}")
        return 400, {"detail": str(e)}


@router.put(
    "/products/{product_id}/identifiers",
    response={200: list[ProductIdentifierSchema], 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def bulk_update_product_identifiers(request: HttpRequest, product_id: str, payload: ProductIdentifierBulkUpdateSchema):
    """Bulk update product identifiers - replaces all existing identifiers."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can manage product identifiers"}

    # Check billing plan restrictions - product identifiers only for business and enterprise
    if is_billing_enabled() and product.team.billing_plan == "community":
        return 403, {
            "detail": (
                "Product identifiers are only available for business and enterprise plans. "
                "Upgrade your plan to access this feature."
            ),
            "error_code": ErrorCode.BILLING_LIMIT_EXCEEDED,
        }

    try:
        with transaction.atomic():
            # Import here to avoid issues
            from sboms.models import ProductIdentifier

            # Delete all existing identifiers
            product.identifiers.all().delete()

            # Create new identifiers
            new_identifiers = []
            for identifier_data in payload.identifiers:
                identifier = ProductIdentifier.objects.create(
                    product=product,
                    identifier_type=identifier_data.identifier_type,
                    value=identifier_data.value,
                )
                new_identifiers.append(identifier)

        return 200, [
            {
                "id": identifier.id,
                "identifier_type": identifier.identifier_type,
                "value": identifier.value,
                "created_at": identifier.created_at.isoformat(),
            }
            for identifier in new_identifiers
        ]

    except IntegrityError:
        return 400, {
            "detail": "One or more identifiers already exist in this team",
            "error_code": ErrorCode.DUPLICATE_NAME,
        }
    except Exception as e:
        log.error(f"Error bulk updating product identifiers: {e}")
        return 400, {"detail": str(e), "error_code": ErrorCode.INTERNAL_ERROR}


# =============================================================================
# PRODUCT LINK CRUD ENDPOINTS
# =============================================================================


@router.post(
    "/products/{product_id}/links",
    response={201: ProductLinkSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def create_product_link(request: HttpRequest, product_id: str, payload: ProductLinkCreateSchema):
    """Create a new product link."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can manage product links"}

    try:
        with transaction.atomic():
            # Import here to avoid issues
            from sboms.models import ProductLink

            link = ProductLink.objects.create(
                product=product,
                link_type=payload.link_type,
                title=payload.title,
                url=payload.url,
                description=payload.description,
            )

        return 201, {
            "id": link.id,
            "link_type": link.link_type,
            "title": link.title,
            "url": link.url,
            "description": link.description,
            "created_at": link.created_at.isoformat(),
        }

    except IntegrityError:
        return 400, {
            "detail": (f"A link of type {payload.link_type} " f"with URL '{payload.url}' already exists in this team"),
            "error_code": ErrorCode.DUPLICATE_NAME,
        }
    except Exception as e:
        log.error(f"Error creating product link: {e}")
        return 400, {"detail": str(e), "error_code": ErrorCode.INTERNAL_ERROR}


@router.get(
    "/products/{product_id}/links",
    response={200: list[ProductLinkSchema], 403: ErrorResponse, 404: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def list_product_links(request: HttpRequest, product_id: str):
    """List all links for a product."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    # If product is public, allow unauthenticated access
    if product.is_public:
        pass
    else:
        # For private products, require authentication and team access
        if not request.user or not request.user.is_authenticated:
            return 403, {"detail": "Authentication required for private items"}

        if not verify_item_access(request, product, ["guest", "owner", "admin"]):
            return 403, {"detail": "Forbidden"}

    try:
        links = product.links.all()
        return 200, [
            {
                "id": link.id,
                "link_type": link.link_type,
                "title": link.title,
                "url": link.url,
                "description": link.description,
                "created_at": link.created_at.isoformat(),
            }
            for link in links
        ]
    except Exception as e:
        log.error(f"Error listing product links: {e}")
        return 400, {"detail": str(e)}


@router.put(
    "/products/{product_id}/links/{link_id}",
    response={200: ProductLinkSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def update_product_link(request: HttpRequest, product_id: str, link_id: str, payload: ProductLinkUpdateSchema):
    """Update a product link."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can manage product links"}

    try:
        # Import here to avoid issues
        from sboms.models import ProductLink

        link = ProductLink.objects.get(pk=link_id, product=product)
    except ProductLink.DoesNotExist:
        return 404, {"detail": "Product link not found"}

    try:
        with transaction.atomic():
            link.link_type = payload.link_type
            link.title = payload.title
            link.url = payload.url
            link.description = payload.description
            link.save()

        return 200, {
            "id": link.id,
            "link_type": link.link_type,
            "title": link.title,
            "url": link.url,
            "description": link.description,
            "created_at": link.created_at.isoformat(),
        }

    except IntegrityError:
        return 400, {
            "detail": (f"A link of type {payload.link_type} " f"with URL '{payload.url}' already exists in this team")
        }
    except Exception as e:
        log.error(f"Error updating product link {link_id}: {e}")
        return 400, {"detail": str(e)}


@router.delete(
    "/products/{product_id}/links/{link_id}",
    response={204: None, 403: ErrorResponse, 404: ErrorResponse},
)
def delete_product_link(request: HttpRequest, product_id: str, link_id: str):
    """Delete a product link."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can manage product links"}

    try:
        # Import here to avoid issues
        from sboms.models import ProductLink

        link = ProductLink.objects.get(pk=link_id, product=product)
    except ProductLink.DoesNotExist:
        return 404, {"detail": "Product link not found"}

    try:
        link.delete()
        return 204, None
    except Exception as e:
        log.error(f"Error deleting product link {link_id}: {e}")
        return 400, {"detail": str(e)}


@router.put(
    "/products/{product_id}/links",
    response={200: list[ProductLinkSchema], 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def bulk_update_product_links(request: HttpRequest, product_id: str, payload: ProductLinkBulkUpdateSchema):
    """Bulk update product links - replaces all existing links."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can manage product links"}

    try:
        with transaction.atomic():
            # Import here to avoid issues
            from sboms.models import ProductLink

            # Delete all existing links
            product.links.all().delete()

            # Create new links
            new_links = []
            for link_data in payload.links:
                link = ProductLink.objects.create(
                    product=product,
                    link_type=link_data.link_type,
                    title=link_data.title,
                    url=link_data.url,
                    description=link_data.description,
                )
                new_links.append(link)

        return 200, [
            {
                "id": link.id,
                "link_type": link.link_type,
                "title": link.title,
                "url": link.url,
                "description": link.description,
                "created_at": link.created_at.isoformat(),
            }
            for link in new_links
        ]

    except IntegrityError:
        return 400, {
            "detail": "One or more links already exist in this team",
            "error_code": ErrorCode.DUPLICATE_NAME,
        }
    except Exception as e:
        log.error(f"Error bulk updating product links: {e}")
        return 400, {"detail": str(e), "error_code": ErrorCode.INTERNAL_ERROR}


# =============================================================================
# PROJECT CRUD ENDPOINTS
# =============================================================================


@router.post(
    "/projects",
    response={201: ProjectResponseSchema, 400: ErrorResponse, 403: ErrorResponse},
)
def create_project(request: HttpRequest, payload: ProjectCreateSchema):
    """Create a new project."""
    team_id = _get_user_team_id(request)
    if not team_id:
        return 403, {"detail": "No current team selected", "error_code": ErrorCode.NO_CURRENT_TEAM}

    # Check billing limits
    can_create, error_msg, error_code = _check_billing_limits(team_id, "project")
    if not can_create:
        return 403, {"detail": error_msg, "error_code": error_code}

    try:
        # Check if user has permission to create projects in this team
        team = Team.objects.get(id=team_id)
        if not verify_item_access(request, team, ["owner", "admin"]):
            return 403, {"detail": "Only owners and admins can create projects", "error_code": ErrorCode.FORBIDDEN}

        with transaction.atomic():
            project = Project.objects.create(
                name=payload.name,
                team_id=team_id,
                metadata=payload.metadata,
            )

        return 201, _build_item_response(project, "project")

    except IntegrityError:
        return 400, {
            "detail": "A project with this name already exists in this team",
            "error_code": ErrorCode.DUPLICATE_NAME,
        }
    except Team.DoesNotExist:
        return 403, {"detail": "Team not found"}
    except Exception as e:
        log.error(f"Error creating project: {e}")
        return 400, {"detail": str(e)}


@router.get(
    "/projects",
    response={200: list[ProjectResponseSchema], 403: ErrorResponse},
)
def list_projects(request: HttpRequest):
    """List all projects for the current user's team."""
    team_id = _get_user_team_id(request)
    if not team_id:
        return 403, {"detail": "No current team selected"}

    try:
        projects = Project.objects.filter(team_id=team_id).prefetch_related("components")
        return 200, [_build_item_response(project, "project") for project in projects]
    except Exception as e:
        log.error(f"Error listing projects: {e}")
        return 400, {"detail": str(e)}


@router.get(
    "/projects/{project_id}",
    response={200: ProjectResponseSchema, 403: ErrorResponse, 404: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def get_project(request: HttpRequest, project_id: str):
    """Get a specific project by ID."""
    try:
        project = Project.objects.prefetch_related("components").get(pk=project_id)
    except Project.DoesNotExist:
        return 404, {"detail": "Project not found"}

    # If project is public, allow unauthenticated access
    if project.is_public:
        return 200, _build_item_response(project, "project")

    # For private projects, require authentication and team access
    if not request.user or not request.user.is_authenticated:
        return 403, {"detail": "Authentication required for private items"}

    if not verify_item_access(request, project, ["guest", "owner", "admin"]):
        return 403, {"detail": "Forbidden"}

    return 200, _build_item_response(project, "project")


@router.put(
    "/projects/{project_id}",
    response={200: ProjectResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def update_project(request: HttpRequest, project_id: str, payload: ProjectUpdateSchema):
    """Update a project."""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return 404, {"detail": "Project not found"}

    if not verify_item_access(request, project, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can update projects"}

    try:
        with transaction.atomic():
            project.name = payload.name
            project.is_public = payload.is_public
            project.metadata = payload.metadata
            project.save()

        return 200, _build_item_response(project, "project")

    except IntegrityError:
        return 400, {"detail": "A project with this name already exists in this team"}
    except Exception as e:
        log.error(f"Error updating project {project_id}: {e}")
        return 400, {"detail": str(e)}


@router.patch(
    "/projects/{project_id}",
    response={200: ProjectResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def patch_project(request: HttpRequest, project_id: str, payload: ProjectPatchSchema):
    """Partially update a project."""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return 404, {"detail": "Project not found"}

    if not verify_item_access(request, project, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can update projects"}

    try:
        with transaction.atomic():
            # Handle relationship updates separately
            update_data = payload.model_dump(exclude_unset=True)
            component_ids = update_data.pop("component_ids", None)

            # Validate public/private constraints before making changes
            new_is_public = update_data.get("is_public", project.is_public)

            # Check billing plan restrictions when trying to make items private
            if not new_is_public and project.is_public:
                # Get the team from the project
                team = project.team

                # Only enforce billing restrictions if billing is enabled
                if is_billing_enabled() and team.billing_plan == "community":
                    return 403, {
                        "detail": (
                            "Community plan users cannot make items private. "
                            "Upgrade to a paid plan to enable private items."
                        )
                    }

            # If making project public, check if it has private components
            if new_is_public and not project.is_public:
                private_components = project.components.filter(is_public=False)
                if private_components.exists():
                    component_names = ", ".join(private_components.values_list("name", flat=True))
                    return 400, {
                        "detail": (
                            f"Cannot make project public because it contains private components: {component_names}. "
                            "Please make all components public first."
                        )
                    }

            # If making project private, check if it's assigned to any public products
            if not new_is_public and project.is_public:
                public_products = project.product_set.filter(is_public=True)
                if public_products.exists():
                    product_names = ", ".join(public_products.values_list("name", flat=True))
                    return 400, {
                        "detail": (
                            f"Cannot make project private because it's assigned to public products: {product_names}. "
                            "Please remove it from these products first or make the products private."
                        )
                    }

            # If updating component relationships, validate constraints
            if component_ids is not None:
                # Verify all components exist and belong to the same team
                components = Component.objects.filter(id__in=component_ids, team_id=project.team_id)
                if len(components) != len(component_ids):
                    return 400, {"detail": "Some components were not found or don't belong to this team"}

                # Verify access to all components
                for component in components:
                    if not verify_item_access(request, component, ["owner", "admin"]):
                        return 403, {"detail": f"No permission to modify component {component.name}"}

                # If project is (or will be) public, ensure no private components are being assigned
                if new_is_public:
                    private_components = [c for c in components if not c.is_public]
                    if private_components:
                        component_names = ", ".join([c.name for c in private_components])
                        return 400, {
                            "detail": (
                                f"Cannot assign private components to a public project: {component_names}. "
                                "Please make these components public first or keep the project private."
                            )
                        }

                # Update relationships
                project.components.set(components)

            # Update simple fields
            for field, value in update_data.items():
                setattr(project, field, value)
            project.save()

        return 200, _build_item_response(project, "project")

    except IntegrityError:
        return 400, {"detail": "A project with this name already exists in this team"}
    except Exception as e:
        log.error(f"Error patching project {project_id}: {e}")
        return 400, {"detail": str(e)}


@router.delete(
    "/projects/{project_id}",
    response={204: None, 403: ErrorResponse, 404: ErrorResponse},
)
def delete_project(request: HttpRequest, project_id: str):
    """Delete a project."""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return 404, {"detail": "Project not found"}

    if not verify_item_access(request, project, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can delete projects"}

    try:
        project.delete()
        return 204, None
    except Exception as e:
        log.error(f"Error deleting project {project_id}: {e}")
        return 400, {"detail": str(e)}


# =============================================================================
# COMPONENT CRUD ENDPOINTS
# =============================================================================


@router.post(
    "/components",
    response={201: ComponentResponseSchema, 400: ErrorResponse, 403: ErrorResponse},
)
def create_component(request: HttpRequest, payload: ComponentCreateSchema):
    """Create a new component."""
    team_id = _get_user_team_id(request)
    if not team_id:
        return 403, {"detail": "No current team selected", "error_code": ErrorCode.NO_CURRENT_TEAM}

    # Check billing limits
    can_create, error_msg, error_code = _check_billing_limits(team_id, "component")
    if not can_create:
        return 403, {"detail": error_msg, "error_code": error_code}

    try:
        # Check if user has permission to create components in this team
        team = Team.objects.get(id=team_id)
        if not verify_item_access(request, team, ["owner", "admin"]):
            return 403, {"detail": "Only owners and admins can create components", "error_code": ErrorCode.FORBIDDEN}

        with transaction.atomic():
            component = Component.objects.create(
                name=payload.name,
                team_id=team_id,
                component_type=payload.component_type,
                metadata=payload.metadata,
            )

        return 201, _build_item_response(component, "component")

    except IntegrityError:
        return 400, {
            "detail": "A component with this name already exists in this team",
            "error_code": ErrorCode.DUPLICATE_NAME,
        }
    except Team.DoesNotExist:
        return 403, {"detail": "Team not found", "error_code": ErrorCode.TEAM_NOT_FOUND}
    except Exception as e:
        log.error(f"Error creating component: {e}")
        return 400, {"detail": str(e), "error_code": ErrorCode.INTERNAL_ERROR}


@router.get(
    "/components",
    response={200: list[ComponentResponseSchema], 403: ErrorResponse},
)
def list_components(request: HttpRequest):
    """List all components for the current user's team."""
    team_id = _get_user_team_id(request)
    if not team_id:
        return 403, {"detail": "No current team selected"}

    try:
        components = Component.objects.filter(team_id=team_id).prefetch_related("sbom_set")
        return 200, [_build_item_response(component, "component") for component in components]
    except Exception as e:
        log.error(f"Error listing components: {e}")
        return 400, {"detail": str(e)}


@router.get(
    "/components/{component_id}",
    response={200: ComponentResponseSchema, 403: ErrorResponse, 404: ErrorResponse},
)
def get_component(request: HttpRequest, component_id: str):
    """Get a specific component by ID."""
    try:
        component = Component.objects.prefetch_related("sbom_set").get(pk=component_id)
    except Component.DoesNotExist:
        return 404, {"detail": "Component not found"}

    if not verify_item_access(request, component, ["guest", "owner", "admin"]):
        return 403, {"detail": "Forbidden"}

    return 200, _build_item_response(component, "component")


@router.put(
    "/components/{component_id}",
    response={200: ComponentResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def update_component(request: HttpRequest, component_id: str, payload: ComponentUpdateSchema):
    """Update a component."""
    try:
        component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return 404, {"detail": "Component not found"}

    if not verify_item_access(request, component, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can update components"}

    try:
        with transaction.atomic():
            component.name = payload.name
            component.component_type = payload.component_type
            component.is_public = payload.is_public
            component.metadata = payload.metadata
            component.save()

        return 200, _build_item_response(component, "component")

    except IntegrityError:
        return 400, {"detail": "A component with this name already exists in this team"}
    except Exception as e:
        log.error(f"Error updating component {component_id}: {e}")
        return 400, {"detail": str(e)}


@router.patch(
    "/components/{component_id}",
    response={200: ComponentResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def patch_component(request: HttpRequest, component_id: str, payload: ComponentPatchSchema):
    """Partially update a component."""
    try:
        component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return 404, {"detail": "Component not found"}

    if not verify_item_access(request, component, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can update components"}

    try:
        with transaction.atomic():
            # Validate public/private constraints before making changes
            update_data = payload.model_dump(exclude_unset=True)
            new_is_public = update_data.get("is_public", component.is_public)

            # Check billing plan restrictions when trying to make items private
            if not new_is_public and component.is_public:
                # Get the team from the component
                team = component.team

                # Only enforce billing restrictions if billing is enabled
                if is_billing_enabled() and team.billing_plan == "community":
                    return 403, {
                        "detail": (
                            "Community plan users cannot make items private. "
                            "Upgrade to a paid plan to enable private items."
                        )
                    }

            # If making component private, check if it's assigned to any public projects
            if not new_is_public and component.is_public:
                public_projects = component.project_set.filter(is_public=True)
                if public_projects.exists():
                    project_names = ", ".join(public_projects.values_list("name", flat=True))
                    return 400, {
                        "detail": (
                            f"Cannot make component private because it's assigned to public projects: "
                            f"{project_names}. Please remove it from these projects first or make the "
                            f"projects private."
                        )
                    }

            # Only update fields that were provided
            for field, value in update_data.items():
                setattr(component, field, value)
            component.save()

        return 200, _build_item_response(component, "component")

    except IntegrityError:
        return 400, {"detail": "A component with this name already exists in this team"}
    except Exception as e:
        log.error(f"Error patching component {component_id}: {e}")
        return 400, {"detail": str(e)}


@router.delete(
    "/components/{component_id}",
    response={204: None, 403: ErrorResponse, 404: ErrorResponse},
)
def delete_component(request: HttpRequest, component_id: str):
    """Delete a component."""
    try:
        component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return 404, {"detail": "Component not found"}

    if not verify_item_access(request, component, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can delete components"}

    try:
        # Delete associated SBOMs from S3 storage
        sboms = component.sbom_set.all()
        s3 = S3Client("SBOMS") if sboms.exists() else None

        for sbom in sboms:
            if sbom.sbom_filename and s3:
                try:
                    s3.delete_object(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, sbom.sbom_filename)
                except Exception as e:
                    log.warning(f"Failed to delete SBOM file {sbom.sbom_filename} from S3: {str(e)}")

        # Delete the component (CASCADE will handle related objects)
        component.delete()
        return 204, None
    except Exception as e:
        log.error(f"Error deleting component {component_id}: {e}")
        return 400, {"detail": str(e)}


# =============================================================================
# COMPONENT METADATA ENDPOINTS
# =============================================================================


@router.get(
    "/components/{component_id}/metadata",
    response={
        200: ComponentMetaData,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
    exclude_none=True,
    auth=None,
)
@decorate_view(optional_auth)
def get_component_metadata(request, component_id: str):
    """Get metadata for a component."""
    try:
        component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return 404, {"detail": "Component not found"}

    if not verify_item_access(request, component, ["guest", "owner", "admin"]):
        return 403, {"detail": "Forbidden"}

    metadata = component.metadata or {}

    # Remove extra fields from contacts and authors
    def strip_extra_fields(obj_list):
        allowed = {"name", "email", "phone"}
        return [
            {k: v for k, v in obj.items() if k in allowed and v is not None}
            for obj in obj_list
            if isinstance(obj, dict)
        ]

    supplier = metadata.get("supplier", {})
    if "contacts" in supplier:
        supplier["contacts"] = strip_extra_fields(supplier["contacts"])
    metadata["supplier"] = supplier

    if "authors" in metadata:
        metadata["authors"] = strip_extra_fields(metadata["authors"])

    # Include component id and name in the response
    metadata["id"] = component.id
    metadata["name"] = component.name

    return metadata


@router.patch(
    "/components/{component_id}/metadata",
    response={
        204: None,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
)
def patch_component_metadata(request, component_id: str, metadata: ComponentMetaDataPatch):
    """Partially update metadata for a component."""
    log.debug(f"Incoming metadata payload for component {component_id}: {request.body}")
    try:
        component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return 404, {"detail": "Component not found"}

    if not verify_item_access(request, component, ["owner", "admin"]):
        return 403, {"detail": "Forbidden"}

    try:
        # Get existing metadata
        existing_metadata = component.metadata or {}

        # Convert incoming metadata to dict, excluding unset fields
        meta_dict = metadata.model_dump(exclude_unset=True)

        # Only process licenses if they were explicitly provided in the request
        if "licenses" in meta_dict:
            licenses = meta_dict.get("licenses", [])
            if licenses is None:
                licenses = []
            meta_dict["licenses"] = licenses

        # Merge with existing metadata
        updated_metadata = {**existing_metadata, **meta_dict}

        log.debug(f"Final metadata to be saved: {updated_metadata}")
        component.metadata = updated_metadata
        component.save()
        return 204, None
    except ValidationError as ve:
        log.error(f"Pydantic validation error for component {component_id}: {ve.errors()}")
        log.error(f"Failed validation data: {metadata.model_dump()}")
        return 422, {"detail": str(ve.errors())}
    except Exception as e:
        log.error(f"Error updating component metadata for {component_id}: {e}", exc_info=True)
        return 400, {"detail": str(e)}


@router.get(
    "/components/{component_id}/releases",
    response={200: list[dict], 403: ErrorResponse, 404: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def list_component_releases(request: HttpRequest, component_id: str):
    """List all releases that contain this component."""
    try:
        component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return 404, {"detail": "Component not found"}

    # If component is public, allow unauthenticated access
    if not component.is_public:
        if not request.user or not request.user.is_authenticated:
            return 403, {"detail": "Authentication required for private components"}
        if not verify_item_access(request, component, ["guest", "owner", "admin"]):
            return 403, {"detail": "Access denied"}

    try:
        # Find all releases that have artifacts from this component
        # This includes both SBOM and document artifacts
        from documents.models import Document
        from sboms.models import SBOM

        # Get SBOMs for this component
        sbom_ids = SBOM.objects.filter(component_id=component_id).values_list("id", flat=True)

        # Get Documents for this component
        document_ids = Document.objects.filter(component_id=component_id).values_list("id", flat=True)

        # Find releases that have artifacts from either SBOMs or Documents of this component
        release_ids = set()

        # Add releases that contain SBOMs from this component
        sbom_releases = ReleaseArtifact.objects.filter(sbom_id__in=sbom_ids).values_list("release_id", flat=True)
        release_ids.update(sbom_releases)

        # Add releases that contain Documents from this component
        document_releases = ReleaseArtifact.objects.filter(document_id__in=document_ids).values_list(
            "release_id", flat=True
        )
        release_ids.update(document_releases)

        # Get the actual release objects
        releases = Release.objects.filter(id__in=release_ids).select_related("product").order_by("-created_at")

        response_data = []
        for release in releases:
            # Only include public releases if this is a public view (unauthenticated)
            if not request.user.is_authenticated and not release.product.is_public:
                continue

            # Count artifacts for this release
            artifact_count = release.artifacts.count()

            # Check if release has SBOMs for download capability
            has_sboms = release.artifacts.filter(sbom__isnull=False).exists()

            response_data.append(
                {
                    "id": str(release.id),
                    "name": release.name,
                    "description": release.description or "",
                    "product_id": str(release.product.id),
                    "product_name": release.product.name,
                    "is_latest": release.is_latest,
                    "is_prerelease": release.is_prerelease,
                    "is_public": release.product.is_public,  # Inherit from product
                    "created_at": release.created_at,
                    "artifacts_count": artifact_count,
                    "has_sboms": has_sboms,
                    "product": {
                        "id": str(release.product.id),
                        "name": release.product.name,
                    },
                }
            )

        return 200, response_data

    except Exception as e:
        log.error(f"Error listing releases for component {component_id}: {e}")
        return 400, {"detail": str(e)}


# =============================================================================
# DASHBOARD ENDPOINTS
# =============================================================================


@router.get(
    "/dashboard/summary",
    response={200: DashboardStatsResponse, 403: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def get_dashboard_summary(
    request: HttpRequest,
    component_id: str | None = Query(None),
    product_id: str | None = Query(None),
    project_id: str | None = Query(None),
):
    """Retrieve a summary of SBOM statistics and latest uploads for the user's teams."""
    # For specific public items, allow unauthenticated access
    if product_id:
        try:
            product = Product.objects.get(pk=product_id)
            if product.is_public:
                # Allow unauthenticated access for public product stats
                pass
            else:
                # Private product requires authentication
                if not request.user or not request.user.is_authenticated:
                    return 403, {"detail": "Authentication required for private items"}
        except Product.DoesNotExist:
            return 404, {"detail": "Product not found"}
    elif project_id:
        try:
            project = Project.objects.get(pk=project_id)
            if project.is_public:
                # Allow unauthenticated access for public project stats
                pass
            else:
                # Private project requires authentication
                if not request.user or not request.user.is_authenticated:
                    return 403, {"detail": "Authentication required for private items"}
        except Project.DoesNotExist:
            return 404, {"detail": "Project not found"}
    elif component_id:
        try:
            component = Component.objects.get(pk=component_id)
            if component.is_public:
                # Allow unauthenticated access for public component stats
                pass
            else:
                # Private component requires authentication
                if not request.user or not request.user.is_authenticated:
                    return 403, {"detail": "Authentication required for private items"}
        except Component.DoesNotExist:
            return 404, {"detail": "Component not found"}
    else:
        # General dashboard access requires authentication
        if not request.user or not request.user.is_authenticated:
            return 403, {"detail": "Authentication required."}

    # For authenticated users, use their teams; for public access, filter differently
    if request.user and request.user.is_authenticated:
        user_teams_qs = Team.objects.filter(member__user=request.user)
        # Base querysets for the user's teams
        products_qs = Product.objects.filter(team__in=user_teams_qs)
        projects_qs = Project.objects.filter(team__in=user_teams_qs)
        components_qs = Component.objects.filter(team__in=user_teams_qs)
    else:
        # For unauthenticated public access, create empty querysets (will be filtered by specific item below)
        products_qs = Product.objects.none()
        projects_qs = Project.objects.none()
        components_qs = Component.objects.none()

    # Import SBOM here to avoid circular import
    from sboms.models import SBOM

    latest_sboms_qs = SBOM.objects.filter(component__team__in=user_teams_qs).select_related("component")

    # Apply context-specific filtering
    if product_id:
        # When viewing a product, show projects and components within that product
        products_qs = products_qs.filter(id=product_id)
        projects_qs = projects_qs.filter(products__id=product_id)
        components_qs = components_qs.filter(projects__products__id=product_id)
        latest_sboms_qs = latest_sboms_qs.filter(component__projects__products__id=product_id)
    elif project_id:
        # When viewing a project, show components within that project
        projects_qs = projects_qs.filter(id=project_id)
        components_qs = components_qs.filter(projects__id=project_id)
        latest_sboms_qs = latest_sboms_qs.filter(component__projects__id=project_id)
    elif component_id:
        # When viewing a component, filter SBOMs for that component only
        components_qs = components_qs.filter(id=component_id)
        latest_sboms_qs = latest_sboms_qs.filter(component_id=component_id)

    # Get counts
    total_products = products_qs.count()
    total_projects = projects_qs.count()
    total_components = components_qs.count()

    # Get latest uploads
    latest_sboms_qs = latest_sboms_qs.order_by("-created_at")[:5]

    latest_uploads_data = [
        DashboardSBOMUploadInfo(
            component_name=sbom.component.name,
            sbom_name=sbom.name,
            sbom_version=sbom.version,
            created_at=sbom.created_at,
        )
        for sbom in latest_sboms_qs
    ]

    return 200, DashboardStatsResponse(
        total_products=total_products,
        total_projects=total_projects,
        total_components=total_components,
        latest_uploads=latest_uploads_data,
    )


@router.get(
    "/projects/{project_id}/download",
    response={200: None, 403: ErrorResponse, 404: ErrorResponse},
    auth=None,  # Allow unauthenticated access for public projects
)
@decorate_view(optional_token_auth)
def download_project_sbom(request: HttpRequest, project_id: str):
    """Download the consolidated SBOM for a project."""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return 404, {"detail": "Project not found"}

    # Check access permissions
    if not project.is_public:
        if not request.user or not request.user.is_authenticated:
            return 403, {"detail": "Authentication required for private projects"}
        if not verify_item_access(request, project, ["guest", "owner", "admin"]):
            return 403, {"detail": "Access denied"}

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            sbom_path = get_project_sbom_package(project, Path(temp_dir))

            response = HttpResponse(open(sbom_path, "rb").read(), content_type="application/json")
            response["Content-Disposition"] = f"attachment; filename={project.name}.cdx.json"

            return response
    except Exception as e:
        log.error(f"Error generating project SBOM {project_id}: {e}")
        return 500, {"detail": f"Error generating project SBOM: {str(e)}"}


@router.get(
    "/products/{product_id}/download",
    response={200: None, 403: ErrorResponse, 404: ErrorResponse},
    auth=None,  # Allow unauthenticated access for public products
)
@decorate_view(optional_token_auth)
def download_product_sbom(request: HttpRequest, product_id: str):
    """Download the consolidated SBOM for a product."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    # Check access permissions
    if not product.is_public:
        if not request.user or not request.user.is_authenticated:
            return 403, {"detail": "Authentication required for private products"}
        if not verify_item_access(request, product, ["guest", "owner", "admin"]):
            return 403, {"detail": "Access denied"}

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            sbom_path = get_product_sbom_package(product, Path(temp_dir))

            response = HttpResponse(open(sbom_path, "rb").read(), content_type="application/json")
            response["Content-Disposition"] = f"attachment; filename={product.name}.cdx.json"

            return response
    except Exception as e:
        log.error(f"Error generating product SBOM {product_id}: {e}")
        return 500, {"detail": f"Error generating product SBOM: {str(e)}"}


# =============================================================================
# RELEASE CRUD ENDPOINTS
# =============================================================================


@router.get(
    "/releases",
    response={200: list[dict], 403: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def list_all_releases(request: HttpRequest, product_id: str | None = Query(None)):
    """List all releases across all products for the current user's team, optionally filtered by product."""
    team_id = _get_user_team_id(request)
    if not team_id:
        return 403, {"detail": "No current team selected"}

    try:
        # Build the base query for releases belonging to the user's team
        query = Release.objects.filter(product__team_id=team_id).select_related("product")

        # Filter by product if specified
        if product_id:
            query = query.filter(product_id=product_id)
            # Ensure latest release exists for the specific product when filtering
            try:
                product = Product.objects.get(pk=product_id, team_id=team_id)
                _ensure_latest_release_exists(product)
            except Product.DoesNotExist:
                pass  # Product not found or doesn't belong to team, ignore
        else:
            # Ensure latest releases exist for all team products when listing all releases
            team_products = Product.objects.filter(team_id=team_id)
            for product in team_products:
                _ensure_latest_release_exists(product)

        releases = query.order_by("-created_at")

        response_data = []
        for release in releases:
            # Count artifacts for this release
            artifact_count = release.artifacts.count()

            # Check if release has SBOMs for download capability
            has_sboms = release.artifacts.filter(sbom__isnull=False).exists()

            response_data.append(
                {
                    "id": str(release.id),
                    "name": release.name,
                    "description": release.description or "",
                    "product_id": str(release.product.id),
                    "product_name": release.product.name,
                    "is_latest": release.is_latest,
                    "is_prerelease": release.is_prerelease,
                    "is_public": release.product.is_public,  # Inherit from product
                    "created_at": release.created_at,
                    "artifacts_count": artifact_count,
                    "has_sboms": has_sboms,
                    "product": {
                        "id": str(release.product.id),
                        "name": release.product.name,
                    },
                }
            )

        return 200, response_data

    except Exception as e:
        log.error(f"Error listing all releases: {e}")
        return 400, {"detail": str(e)}


def _build_release_response(release: Release, include_artifacts: bool = False) -> dict:
    """Build a standardized response for releases."""
    response = {
        "id": release.id,
        "name": release.name,
        "description": release.description,
        "product_id": str(release.product.id),
        "product_name": release.product.name,
        "is_latest": release.is_latest,
        "is_prerelease": release.is_prerelease,
        "is_public": release.product.is_public,  # Inherit from product
        "created_at": release.created_at.isoformat(),
        "artifact_count": release.artifacts.count(),
    }

    if include_artifacts:
        artifacts = []
        for artifact in release.artifacts.select_related("sbom__component", "document__component"):
            if artifact.sbom:
                artifacts.append(
                    {
                        "id": artifact.id,
                        "artifact_type": "sbom",
                        "artifact_name": artifact.sbom.name,
                        "component_id": str(artifact.sbom.component.id),
                        "component_name": artifact.sbom.component.name,
                        "created_at": artifact.created_at.isoformat(),
                        "sbom_format": artifact.sbom.format,
                        "sbom_version": artifact.sbom.version,
                        "document_type": None,
                        "document_version": None,
                    }
                )
            elif artifact.document:
                artifacts.append(
                    {
                        "id": artifact.id,
                        "artifact_type": "document",
                        "artifact_name": artifact.document.name,
                        "component_id": str(artifact.document.component.id),
                        "component_name": artifact.document.component.name,
                        "created_at": artifact.created_at.isoformat(),
                        "sbom_format": None,
                        "sbom_version": None,
                        "document_type": artifact.document.document_type,
                        "document_version": artifact.document.version,
                    }
                )
        response["artifacts"] = artifacts

    return response


# =============================================================================
# TOP-LEVEL RELEASE CRUD ENDPOINTS
# =============================================================================


@router.post(
    "/releases",
    response={201: ReleaseResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def create_release(request: HttpRequest, payload: ReleaseCreateSchema):
    """Create a new release."""
    from core.models import LATEST_RELEASE_NAME

    try:
        product = Product.objects.get(pk=payload.product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can create releases"}

    # Prevent creating releases with name "latest" manually
    if payload.name.lower() == LATEST_RELEASE_NAME.lower():
        return 400, {
            "detail": (
                f"Cannot create release with name '{LATEST_RELEASE_NAME}'. "
                "This name is reserved for the auto-managed latest release."
            )
        }

    try:
        with transaction.atomic():
            release = Release.objects.create(
                product=product,
                name=payload.name,
                description=payload.description or "",
                is_latest=False,  # Manual releases are never latest
                is_prerelease=payload.is_prerelease,
            )

        return 201, _build_release_response(release, include_artifacts=True)

    except IntegrityError:
        return 400, {"detail": "A release with this name already exists for this product"}
    except Exception as e:
        log.error(f"Error creating release: {e}")
        return 400, {"detail": str(e)}


@router.get(
    "/releases/{release_id}",
    response={200: ReleaseResponseSchema, 403: ErrorResponse, 404: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def get_release(request: HttpRequest, release_id: str):
    """Get a specific release by ID."""
    try:
        release = Release.objects.select_related("product").prefetch_related("artifacts").get(pk=release_id)
    except Release.DoesNotExist:
        return 404, {"detail": "Release not found"}

    # If product is public, allow unauthenticated access
    if not release.product.is_public:
        if not request.user or not request.user.is_authenticated:
            return 403, {"detail": "Authentication required for private products"}
        if not verify_item_access(request, release.product, ["guest", "owner", "admin"]):
            return 403, {"detail": "Access denied"}

    return 200, _build_release_response(release, include_artifacts=True)


@router.put(
    "/releases/{release_id}",
    response={200: ReleaseResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def update_release(request: HttpRequest, release_id: str, payload: ReleaseUpdateSchema):
    """Update a release."""
    from core.models import LATEST_RELEASE_NAME

    try:
        release = Release.objects.select_related("product").get(pk=release_id)
    except Release.DoesNotExist:
        return 404, {"detail": "Release not found"}

    if not verify_item_access(request, release.product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can update releases"}

    # Prevent modifying latest releases
    if release.is_latest:
        return 400, {
            "detail": f"Cannot modify the '{LATEST_RELEASE_NAME}' release. This release is automatically managed."
        }

    # Prevent renaming to "latest"
    if payload.name.lower() == LATEST_RELEASE_NAME.lower():
        return 400, {
            "detail": (
                f"Cannot rename a release to '{LATEST_RELEASE_NAME}'. "
                "This name is reserved for automatically managed releases."
            )
        }

    try:
        with transaction.atomic():
            release.name = payload.name
            release.description = payload.description or ""
            release.is_prerelease = payload.is_prerelease
            if payload.created_at is not None:
                release.created_at = payload.created_at
            release.save()

        return 200, _build_release_response(release, include_artifacts=True)

    except IntegrityError:
        return 400, {"detail": "A release with this name already exists for this product"}
    except Exception as e:
        log.error(f"Error updating release {release_id}: {e}")
        return 400, {"detail": str(e)}


@router.patch(
    "/releases/{release_id}",
    response={200: ReleaseResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def patch_release(request: HttpRequest, release_id: str, payload: ReleasePatchSchema):
    """Partially update a release."""
    from core.models import LATEST_RELEASE_NAME

    try:
        release = Release.objects.select_related("product").get(pk=release_id)
    except Release.DoesNotExist:
        return 404, {"detail": "Release not found"}

    if not verify_item_access(request, release.product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can update releases"}

    # Prevent modifying latest releases
    if release.is_latest:
        return 400, {
            "detail": f"Cannot modify the '{LATEST_RELEASE_NAME}' release. This release is automatically managed."
        }

    try:
        with transaction.atomic():
            update_data = payload.model_dump(exclude_unset=True)

            # Prevent renaming to "latest"
            if "name" in update_data and update_data["name"].lower() == LATEST_RELEASE_NAME.lower():
                return 400, {
                    "detail": (
                        f"Cannot rename a release to '{LATEST_RELEASE_NAME}'. This name is reserved for "
                        "automatically managed releases."
                    )
                }

            # Update only fields that have actually changed to avoid unnecessary unique constraint checks
            changed = False
            for field, value in update_data.items():
                current_value = getattr(release, field)
                if current_value != value:
                    setattr(release, field, value)
                    changed = True

            # Only save if something actually changed
            if changed:
                release.save()

        return 200, _build_release_response(release, include_artifacts=True)

    except IntegrityError:
        return 400, {"detail": "A release with this name already exists for this product"}
    except Exception as e:
        log.error(f"Error patching release {release_id}: {e}")
        return 400, {"detail": str(e)}


@router.delete(
    "/releases/{release_id}",
    response={204: None, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def delete_release(request: HttpRequest, release_id: str):
    """Delete a release."""
    from core.models import LATEST_RELEASE_NAME

    try:
        release = Release.objects.select_related("product").get(pk=release_id)
    except Release.DoesNotExist:
        return 404, {"detail": "Release not found"}

    if not verify_item_access(request, release.product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can delete releases"}

    # Prevent deleting latest releases
    if release.is_latest:
        return 400, {
            "detail": f"Cannot delete the '{LATEST_RELEASE_NAME}' release. This release is automatically managed."
        }

    try:
        release.delete()
        return 204, None
    except Exception as e:
        log.error(f"Error deleting release {release_id}: {e}")
        return 400, {"detail": str(e)}


# =============================================================================
# RELEASE DOWNLOAD ENDPOINT
# =============================================================================


@router.get(
    "/releases/{release_id}/download",
    response={200: None, 403: ErrorResponse, 404: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def download_release(request: HttpRequest, release_id: str):
    """Download release SBOM."""
    try:
        release = Release.objects.select_related("product").get(pk=release_id)
    except Release.DoesNotExist:
        return 404, {"detail": "Release not found"}

    # If product is public, allow unauthenticated access
    if not release.product.is_public:
        if not request.user or not request.user.is_authenticated:
            return 403, {"detail": "Authentication required"}

        team_id = _get_user_team_id(request)
        if not team_id or str(team_id) != str(release.product.team_id):
            return 403, {"detail": "Access denied"}

    # Get all SBOM artifacts in the release
    sbom_artifacts = release.artifacts.filter(sbom__isnull=False).select_related("sbom")

    if not sbom_artifacts.exists():
        return HttpResponse(
            status=500, content='{"detail": "Error generating release SBOM"}', content_type="application/json"
        )

    try:
        # Use the SBOM package generator
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            sbom_file_path = get_release_sbom_package(release, temp_path)

            # Read the generated SBOM file
            with open(sbom_file_path, "r") as f:
                sbom_content = f.read()

            response = HttpResponse(sbom_content, content_type="application/json")
            response["Content-Disposition"] = f"attachment; filename={release.product.name}-{release.name}.cdx.json"

            return response

    except Exception as e:
        return HttpResponse(
            status=500,
            content=f'{{"detail": "Error generating release SBOM: {str(e)}"}}',
            content_type="application/json",
        )


# =============================================================================
# ARTIFACT MANAGEMENT ENDPOINTS
# =============================================================================


@router.get(
    "/releases/{release_id}/artifacts",
    response={200: list[dict], 403: ErrorResponse, 404: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def list_release_artifacts(request: HttpRequest, release_id: str, mode: str = Query("available")):
    """
    List artifacts for a release.

    Mode can be 'existing' (artifacts in release) or 'available' (artifacts that can be added).
    """
    try:
        release = Release.objects.select_related("product").get(pk=release_id)
    except Release.DoesNotExist:
        return 404, {"detail": "Release not found"}

    # If product is public, allow unauthenticated access
    if not release.product.is_public:
        if not request.user or not request.user.is_authenticated:
            return 403, {"detail": "Authentication required"}

        team_id = _get_user_team_id(request)
        if not team_id or str(team_id) != str(release.product.team_id):
            return 403, {"detail": "Access denied"}

    if mode == "existing":
        # Return artifacts that are already in this release
        existing_artifacts = ReleaseArtifact.objects.filter(release=release).select_related("sbom", "document")

        artifacts = []
        for artifact in existing_artifacts:
            if artifact.sbom:
                artifacts.append(
                    {
                        "id": str(artifact.id),
                        "artifact_type": "sbom",
                        "artifact_name": artifact.sbom.name,
                        "component_id": str(artifact.sbom.component.id),
                        "component_name": artifact.sbom.component.name,
                        "created_at": artifact.created_at.isoformat(),
                        "sbom_format": artifact.sbom.format,
                        "sbom_version": artifact.sbom.format_version,
                        "document_type": None,
                        "document_version": None,
                    }
                )
            elif artifact.document:
                artifacts.append(
                    {
                        "id": str(artifact.id),
                        "artifact_type": "document",
                        "artifact_name": artifact.document.name,
                        "component_id": str(artifact.document.component.id),
                        "component_name": artifact.document.component.name,
                        "created_at": artifact.created_at.isoformat(),
                        "sbom_format": None,
                        "sbom_version": None,
                        "document_type": artifact.document.document_type,
                        "document_version": artifact.document.version or "",
                    }
                )

        return artifacts

    else:  # mode == "available" (default)
        # Return artifacts that can be added to this release (existing logic)
        from core.models import Component
        from documents.models import Document
        from sboms.models import SBOM

        product_components = Component.objects.filter(
            projects__products=release.product, team_id=release.product.team_id
        ).distinct()

        # Get existing artifacts in this release to exclude them
        existing_sbom_ids = set(
            ReleaseArtifact.objects.filter(release=release, sbom__isnull=False).values_list("sbom_id", flat=True)
        )
        existing_document_ids = set(
            ReleaseArtifact.objects.filter(release=release, document__isnull=False).values_list(
                "document_id", flat=True
            )
        )

        available_artifacts = []

        # Add available SBOMs
        available_sboms = SBOM.objects.filter(component__in=product_components).exclude(id__in=existing_sbom_ids)

        for sbom in available_sboms:
            available_artifacts.append(
                {
                    "id": str(sbom.id),
                    "artifact_type": "sbom",
                    "name": sbom.name,
                    "component": {
                        "id": str(sbom.component.id),
                        "name": sbom.component.name,
                    },
                    "format": sbom.format,
                    "format_version": sbom.format_version,
                    "version": sbom.version or "",
                    "created_at": sbom.created_at.isoformat(),
                }
            )

        # Add available Documents
        available_documents = Document.objects.filter(component__in=product_components).exclude(
            id__in=existing_document_ids
        )

        for document in available_documents:
            available_artifacts.append(
                {
                    "id": str(document.id),
                    "artifact_type": "document",
                    "name": document.name,
                    "component": {
                        "id": str(document.component.id),
                        "name": document.component.name,
                    },
                    "document_type": document.document_type,
                    "version": document.version or "",
                    "created_at": document.created_at.isoformat(),
                }
            )

        return available_artifacts


@router.post(
    "/releases/{release_id}/artifacts",
    response={201: ReleaseArtifactAddResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def add_artifacts_to_release(request: HttpRequest, release_id: str, payload: ReleaseArtifactCreateSchema):
    """Add artifacts to a release."""
    try:
        release = Release.objects.select_related("product").get(pk=release_id)
    except Release.DoesNotExist:
        return 404, {"detail": "Release not found"}

    team_id = _get_user_team_id(request)
    if not team_id or str(team_id) != str(release.product.team_id):
        return 403, {"detail": "Access denied"}

    if not verify_item_access(request, release.product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can manage release artifacts"}

    # Prevent adding artifacts to latest releases
    if release.is_latest:
        return 400, {"detail": "Cannot add artifacts to 'latest' release"}

    from core.utils import add_artifact_to_release

    # Handle SBOM
    if payload.sbom_id:
        try:
            from sboms.models import SBOM

            sbom = SBOM.objects.get(pk=payload.sbom_id)
            if str(sbom.component.team_id) != str(team_id):
                return 403, {"detail": f"SBOM {sbom.name} does not belong to your team"}

            result = add_artifact_to_release(release, sbom=sbom, allow_replacement=False)
            if result.get("error"):
                return 400, {"detail": result["error"]}
            artifact = result["artifact"]

            return 201, {
                "id": str(artifact.id),
                "artifact_type": "sbom",
                "artifact_name": artifact.sbom.name,
                "component_id": str(artifact.sbom.component.id),
                "component_name": artifact.sbom.component.name,
                "created_at": artifact.created_at.isoformat(),
                "sbom_format": artifact.sbom.format,
                "sbom_version": artifact.sbom.format_version,
                "document_type": None,
                "document_version": None,
            }
        except Exception as e:
            return 400, {"detail": f"Error processing SBOM: {str(e)}"}

    # Handle Document
    if payload.document_id:
        try:
            from documents.models import Document

            document = Document.objects.get(pk=payload.document_id)
            if str(document.component.team_id) != str(team_id):
                return 403, {"detail": f"Document {document.name} does not belong to your team"}

            result = add_artifact_to_release(release, document=document, allow_replacement=False)
            if result.get("error"):
                return 400, {"detail": result["error"]}
            artifact = result["artifact"]

            return 201, {
                "id": str(artifact.id),
                "artifact_type": "document",
                "artifact_name": artifact.document.name,
                "component_id": str(artifact.document.component.id),
                "component_name": artifact.document.component.name,
                "created_at": artifact.created_at.isoformat(),
                "sbom_format": None,
                "sbom_version": None,
                "document_type": artifact.document.document_type,
                "document_version": artifact.document.version or "",
            }
        except Exception as e:
            return 400, {"detail": f"Error processing document: {str(e)}"}

    return 400, {"detail": "Either sbom_id or document_id must be provided"}


@router.delete(
    "/releases/{release_id}/artifacts/{artifact_id}",
    response={204: None, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def remove_artifact_from_release(request: HttpRequest, release_id: str, artifact_id: str):
    """Remove an artifact from a release."""
    try:
        release = Release.objects.select_related("product").get(pk=release_id)
    except Release.DoesNotExist:
        return 404, {"detail": "Release not found"}

    try:
        artifact = ReleaseArtifact.objects.get(pk=artifact_id, release=release)
    except ReleaseArtifact.DoesNotExist:
        return 404, {"detail": "Artifact not found in this release"}

    team_id = _get_user_team_id(request)
    if not team_id or str(team_id) != str(release.product.team_id):
        return 403, {"detail": "Access denied"}

    if not verify_item_access(request, release.product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can manage release artifacts"}

    # Prevent removing artifacts from latest releases
    if release.is_latest:
        return 400, {"detail": "Cannot remove artifacts from 'latest' release"}

    artifact.delete()
    return 204, None


# =============================================================================
# REVERSE LOOKUP ENDPOINTS - WHAT RELEASES CONTAIN THESE ARTIFACTS
# =============================================================================


@router.get(
    "/documents/{document_id}/releases",
    response={200: list[dict], 403: ErrorResponse, 404: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def list_document_releases(request: HttpRequest, document_id: str):
    """List all releases that contain this document."""
    try:
        from documents.models import Document

        document = Document.objects.select_related("component").get(pk=document_id)
    except Document.DoesNotExist:
        return 404, {"detail": "Document not found"}

    # If component is public, allow unauthenticated access
    if not document.component.is_public:
        if not request.user or not request.user.is_authenticated:
            return 403, {"detail": "Authentication required"}

        team_id = _get_user_team_id(request)
        if not team_id or str(team_id) != str(document.component.team_id):
            return 403, {"detail": "Access denied"}

    # Get all releases containing this document
    release_artifacts = ReleaseArtifact.objects.filter(document=document).select_related("release", "release__product")

    return [
        {
            "id": str(artifact.release.id),
            "name": artifact.release.name,
            "description": artifact.release.description,
            "is_prerelease": artifact.release.is_prerelease,
            "is_latest": artifact.release.is_latest,
            "product_id": str(artifact.release.product.id),
            "product_name": artifact.release.product.name,
        }
        for artifact in release_artifacts
    ]


@router.post(
    "/documents/{document_id}/releases",
    response={201: DocumentReleaseTaggingResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def add_document_to_releases(request: HttpRequest, document_id: str, payload: DocumentReleaseTaggingSchema):
    """Add a document to multiple releases."""
    try:
        from documents.models import Document

        document = Document.objects.select_related("component").get(pk=document_id)
    except Document.DoesNotExist:
        return 404, {"detail": "Document not found"}

    team_id = _get_user_team_id(request)
    if not team_id or str(team_id) != str(document.component.team_id):
        return 403, {"detail": "Access denied"}

    if not verify_item_access(request, document.component, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can manage document releases"}

    from core.utils import add_artifact_to_release

    created_artifacts = []
    replaced_artifacts = []
    errors = []

    for release_id in payload.release_ids:
        try:
            release = Release.objects.select_related("product").get(pk=release_id)

            # Verify release belongs to same team
            if str(release.product.team_id) != str(team_id):
                errors.append(f"Release {release.name} does not belong to your team")
                continue

            # Prevent adding to latest releases
            if release.is_latest:
                errors.append(f"Cannot add document to 'latest' release {release.name}")
                continue

            result = add_artifact_to_release(release, document=document, allow_replacement=True)
            if result["created"]:
                created_artifacts.append(result["artifact"])
            elif result["replaced"]:
                replaced_artifacts.append(result)
            else:
                errors.append(f"Document already exists in release {release.name}")

        except Release.DoesNotExist:
            errors.append(f"Release {release_id} not found")
        except Exception as e:
            errors.append(f"Error adding to release {release_id}: {str(e)}")

    if not created_artifacts and not replaced_artifacts:
        return 400, {"detail": "No artifacts were created or replaced"}

    return 201, {
        "created_artifacts": [
            {
                "artifact_id": str(artifact.id),
                "release_id": str(artifact.release.id),
                "release_name": artifact.release.name,
                "product_id": str(artifact.release.product.id),
                "product_name": artifact.release.product.name,
                "created_at": artifact.created_at,
            }
            for artifact in created_artifacts
        ],
        "replaced_artifacts": [
            {
                "artifact_id": str(result["artifact"].id),
                "release_id": str(result["artifact"].release.id),
                "release_name": result["artifact"].release.name,
                "product_id": str(result["artifact"].release.product.id),
                "product_name": result["artifact"].release.product.name,
                "created_at": result["artifact"].created_at,
                "replaced_document": result["replaced_info"]["replaced_document"]
                if result.get("replaced_info")
                else None,
            }
            for result in replaced_artifacts
        ],
        "errors": errors,
    }


@router.delete(
    "/documents/{document_id}/releases/{release_id}",
    response={204: None, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def remove_document_from_release(request: HttpRequest, document_id: str, release_id: str):
    """Remove a document from a specific release."""
    try:
        from documents.models import Document

        document = Document.objects.select_related("component").get(pk=document_id)
    except Document.DoesNotExist:
        return 404, {"detail": "Document not found"}

    try:
        release = Release.objects.select_related("product").get(pk=release_id)
    except Release.DoesNotExist:
        return 404, {"detail": "Release not found"}

    team_id = _get_user_team_id(request)
    if not team_id or str(team_id) != str(document.component.team_id):
        return 403, {"detail": "Access denied"}

    if not verify_item_access(request, document.component, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can manage document releases"}

    # Prevent removing from latest releases
    if release.is_latest:
        return 400, {"detail": "Cannot remove document from 'latest' release"}

    try:
        artifact = ReleaseArtifact.objects.get(release=release, document=document)
        artifact.delete()
        return 204, None
    except ReleaseArtifact.DoesNotExist:
        return 404, {"detail": "Document not in this release"}


@router.get(
    "/sboms/{sbom_id}/releases",
    response={200: list[dict], 403: ErrorResponse, 404: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def list_sbom_releases(request: HttpRequest, sbom_id: str):
    """List all releases that contain this SBOM."""
    try:
        from sboms.models import SBOM

        sbom = SBOM.objects.select_related("component").get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return 404, {"detail": "SBOM not found"}

    # If component is public, allow unauthenticated access
    if not sbom.component.is_public:
        if not request.user or not request.user.is_authenticated:
            return 403, {"detail": "Authentication required"}

        team_id = _get_user_team_id(request)
        if not team_id or str(team_id) != str(sbom.component.team_id):
            return 403, {"detail": "Access denied"}

    # Get all releases containing this SBOM
    release_artifacts = ReleaseArtifact.objects.filter(sbom=sbom).select_related("release", "release__product")

    return [
        {
            "id": str(artifact.release.id),
            "name": artifact.release.name,
            "description": artifact.release.description,
            "is_prerelease": artifact.release.is_prerelease,
            "is_latest": artifact.release.is_latest,
            "product_id": str(artifact.release.product.id),
            "product_name": artifact.release.product.name,
        }
        for artifact in release_artifacts
    ]


@router.post(
    "/sboms/{sbom_id}/releases",
    response={201: SBOMReleaseTaggingResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def add_sbom_to_releases(request: HttpRequest, sbom_id: str, payload: SBOMReleaseTaggingSchema):
    """Add an SBOM to multiple releases."""
    try:
        from sboms.models import SBOM

        sbom = SBOM.objects.select_related("component").get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return 404, {"detail": "SBOM not found"}

    team_id = _get_user_team_id(request)
    if not team_id or str(team_id) != str(sbom.component.team_id):
        return 403, {"detail": "Access denied"}

    if not verify_item_access(request, sbom.component, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can manage SBOM releases"}

    from core.utils import add_artifact_to_release

    created_artifacts = []
    replaced_artifacts = []
    errors = []

    for release_id in payload.release_ids:
        try:
            release = Release.objects.select_related("product").get(pk=release_id)

            # Verify release belongs to same team
            if str(release.product.team_id) != str(team_id):
                errors.append(f"Release {release.name} does not belong to your team")
                continue

            # Prevent adding to latest releases
            if release.is_latest:
                errors.append(f"Cannot add SBOM to 'latest' release {release.name}")
                continue

            result = add_artifact_to_release(release, sbom=sbom, allow_replacement=True)
            if result["created"]:
                created_artifacts.append(result["artifact"])
            elif result["replaced"]:
                replaced_artifacts.append(result)
            else:
                errors.append(f"SBOM already exists in release {release.name}")

        except Release.DoesNotExist:
            errors.append(f"Release {release_id} not found")
        except Exception as e:
            errors.append(f"Error adding to release {release_id}: {str(e)}")

    if not created_artifacts and not replaced_artifacts:
        return 400, {"detail": "No artifacts were created or replaced"}

    return 201, {
        "created_artifacts": [
            {
                "artifact_id": str(artifact.id),
                "release_id": str(artifact.release.id),
                "release_name": artifact.release.name,
                "product_id": str(artifact.release.product.id),
                "product_name": artifact.release.product.name,
                "created_at": artifact.created_at,
            }
            for artifact in created_artifacts
        ],
        "replaced_artifacts": [
            {
                "artifact_id": str(result["artifact"].id),
                "release_id": str(result["artifact"].release.id),
                "release_name": result["artifact"].release.name,
                "product_id": str(result["artifact"].release.product.id),
                "product_name": result["artifact"].release.product.name,
                "created_at": result["artifact"].created_at,
                "replaced_sbom": result["replaced_info"]["replaced_sbom"] if result.get("replaced_info") else None,
            }
            for result in replaced_artifacts
        ],
        "errors": errors,
    }


@router.delete(
    "/sboms/{sbom_id}/releases/{release_id}",
    response={204: None, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def remove_sbom_from_release(request: HttpRequest, sbom_id: str, release_id: str):
    """Remove an SBOM from a specific release."""
    try:
        from sboms.models import SBOM

        sbom = SBOM.objects.select_related("component").get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return 404, {"detail": "SBOM not found"}

    try:
        release = Release.objects.select_related("product").get(pk=release_id)
    except Release.DoesNotExist:
        return 404, {"detail": "Release not found"}

    team_id = _get_user_team_id(request)
    if not team_id or str(team_id) != str(sbom.component.team_id):
        return 403, {"detail": "Access denied"}

    # Verify release belongs to same team
    if str(release.product.team_id) != str(team_id):
        return 403, {"detail": "Access denied"}

    if not verify_item_access(request, sbom.component, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can manage SBOM releases"}

    # Prevent removing from latest releases
    if release.is_latest:
        return 400, {"detail": "Cannot remove SBOM from automatically managed release"}

    try:
        artifact = ReleaseArtifact.objects.get(release=release, sbom=sbom)
        artifact.delete()
        return 204, None
    except ReleaseArtifact.DoesNotExist:
        return 404, {"detail": "SBOM not in this release"}

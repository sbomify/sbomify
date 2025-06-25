from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from ninja import Router
from ninja.security import django_auth
from pydantic import BaseModel

from access_tokens.auth import PersonalAccessTokenAuth
from billing.config import is_billing_enabled
from billing.models import BillingPlan
from core.object_store import S3Client
from sbomify.logging import getLogger
from sboms.models import Component, Product, Project
from sboms.schemas import (
    ComponentCreateSchema,
    ComponentPatchSchema,
    ComponentResponseSchema,
    ComponentUpdateSchema,
    ItemTypes,
    ProductCreateSchema,
    ProductPatchSchema,
    ProductProjectLinkSchema,
    ProductResponseSchema,
    ProductUpdateSchema,
    ProjectComponentLinkSchema,
    ProjectCreateSchema,
    ProjectPatchSchema,
    ProjectResponseSchema,
    ProjectUpdateSchema,
    UserItemsResponse,
)
from sboms.utils import verify_item_access
from teams.models import Team
from teams.utils import get_user_teams

from .schemas import ErrorCode, ErrorResponse

log = getLogger(__name__)


# Creation schemas
class CreateItemRequest(BaseModel):
    name: str


class CreateItemResponse(BaseModel):
    id: str


class CreateProjectRequest(BaseModel):
    name: str
    product_id: str


router = Router(tags=["core"], auth=(PersonalAccessTokenAuth(), django_auth))

item_type_map = {"team": Team, "component": Component, "project": Project, "product": Product}


def _get_user_team_id(request: HttpRequest) -> str | None:
    """Get the current user's team ID from the session."""
    from core.utils import get_team_id_from_session

    return get_team_id_from_session(request)


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
    elif item_type == "project":
        base_response["component_count"] = item.components.count()
        base_response["metadata"] = item.metadata
        # Include actual components data for frontend
        base_response["components"] = [
            {
                "id": component.id,
                "name": component.name,
                "is_public": component.is_public,
            }
            for component in item.components.all()
        ]
    elif item_type == "component":
        base_response["sbom_count"] = item.sbom_set.count()
        base_response["metadata"] = item.metadata

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
    user_teams = get_user_teams(user=request.user, include_team_id=True)
    Model = item_type_map[item_type]

    result = []
    team_id_to_key = {v["team_id"]: k for k, v in user_teams.items() if "team_id" in v}
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
        products = Product.objects.filter(team_id=team_id).prefetch_related("projects")
        return 200, [_build_item_response(product, "product") for product in products]
    except Exception as e:
        log.error(f"Error listing products: {e}")
        return 400, {"detail": str(e)}


@router.get(
    "/products/{product_id}",
    response={200: ProductResponseSchema, 403: ErrorResponse, 404: ErrorResponse},
)
def get_product(request: HttpRequest, product_id: str):
    """Get a specific product by ID."""
    try:
        product = Product.objects.prefetch_related("projects").get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

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
            # Only update fields that were provided
            update_data = payload.model_dump(exclude_unset=True)
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


@router.post(
    "/products/{product_id}/projects",
    response={204: None, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def link_projects_to_product(request: HttpRequest, product_id: str, payload: ProductProjectLinkSchema):
    """Link projects to a product."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can link projects to products"}

    try:
        projects = Project.objects.filter(id__in=payload.project_ids, team_id=product.team_id)

        # Verify access to all projects
        for project in projects:
            if not verify_item_access(request, project, ["owner", "admin"]):
                return 403, {"detail": f"No permission to link project {project.name}"}

        with transaction.atomic():
            product.projects.add(*projects)

        return 204, None
    except Exception as e:
        log.error(f"Error linking projects to product {product_id}: {e}")
        return 400, {"detail": str(e)}


@router.delete(
    "/products/{product_id}/projects",
    response={204: None, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def unlink_projects_from_product(request: HttpRequest, product_id: str, payload: ProductProjectLinkSchema):
    """Unlink projects from a product."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found"}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can unlink projects from products"}

    try:
        projects = Project.objects.filter(id__in=payload.project_ids, team_id=product.team_id)

        # Verify access to all projects
        for project in projects:
            if not verify_item_access(request, project, ["owner", "admin"]):
                return 403, {"detail": f"No permission to unlink project {project.name}"}

        with transaction.atomic():
            product.projects.remove(*projects)

        return 204, None
    except Exception as e:
        log.error(f"Error unlinking projects from product {product_id}: {e}")
        return 400, {"detail": str(e)}


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
)
def get_project(request: HttpRequest, project_id: str):
    """Get a specific project by ID."""
    try:
        project = Project.objects.prefetch_related("components").get(pk=project_id)
    except Project.DoesNotExist:
        return 404, {"detail": "Project not found"}

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
            # Only update fields that were provided
            update_data = payload.model_dump(exclude_unset=True)
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


@router.post(
    "/projects/{project_id}/components",
    response={204: None, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def link_components_to_project(request: HttpRequest, project_id: str, payload: ProjectComponentLinkSchema):
    """Link components to a project."""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return 404, {"detail": "Project not found"}

    if not verify_item_access(request, project, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can link components to projects"}

    try:
        components = Component.objects.filter(id__in=payload.component_ids, team_id=project.team_id)

        # Verify access to all components
        for component in components:
            if not verify_item_access(request, component, ["owner", "admin"]):
                return 403, {"detail": f"No permission to link component {component.name}"}

        with transaction.atomic():
            project.components.add(*components)

        return 204, None
    except Exception as e:
        log.error(f"Error linking components to project {project_id}: {e}")
        return 400, {"detail": str(e)}


@router.delete(
    "/projects/{project_id}/components",
    response={204: None, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def unlink_components_from_project(request: HttpRequest, project_id: str, payload: ProjectComponentLinkSchema):
    """Unlink components from a project."""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return 404, {"detail": "Project not found"}

    if not verify_item_access(request, project, ["owner", "admin"]):
        return 403, {"detail": "Only owners and admins can unlink components from projects"}

    try:
        components = Component.objects.filter(id__in=payload.component_ids, team_id=project.team_id)

        # Verify access to all components
        for component in components:
            if not verify_item_access(request, component, ["owner", "admin"]):
                return 403, {"detail": f"No permission to unlink component {component.name}"}

        with transaction.atomic():
            project.components.remove(*components)

        return 204, None
    except Exception as e:
        log.error(f"Error unlinking components from project {project_id}: {e}")
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
            # Only update fields that were provided
            update_data = payload.model_dump(exclude_unset=True)
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

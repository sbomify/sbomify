from django.db import IntegrityError
from ninja import Field, Router, Schema
from ninja.security import django_auth
from pydantic import BaseModel

from access_tokens.auth import PersonalAccessTokenAuth
from core.utils import get_current_team_id
from sboms.models import Component, Product, Project
from sboms.utils import verify_item_access
from teams.models import Team

from .schemas import ErrorResponse


class RenameItemSchema(Schema):
    class Config(Schema.Config):
        str_strip_whitespace = True

    name: str = Field(..., max_length=255, min_length=1)


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


@router.patch(
    "/rename/{item_type}/{item_id}",
    response={
        204: None,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
)
def rename_item(request, item_type: str, item_id: str, payload: RenameItemSchema):
    if item_type not in item_type_map:
        return 400, {"detail": "Invalid item type"}

    Model = item_type_map[item_type]

    if item_type == "team":
        rec = Team.objects.filter(key=item_id).first()
        permissions_required = ["owner"]
    else:
        rec = Model.objects.filter(id=item_id).first()
        permissions_required = ["owner", "admin"]

    if rec is None:
        return 404, {"detail": "Not found"}

    if not verify_item_access(request, rec, permissions_required):
        return 403, {"detail": "Forbidden"}

    rec.name = payload.name
    rec.save()

    return 204, None


@router.post(
    "/product/",
    response={201: CreateItemResponse, 400: ErrorResponse, 403: ErrorResponse},
)
def create_product(request, payload: CreateItemRequest):
    """Create a new product."""
    try:
        team_id = get_current_team_id(request)
        if team_id is None:
            return 400, {"detail": "No current team selected"}

        # Create the product
        product = Product.objects.create(name=payload.name, team_id=team_id)
        return 201, {"id": product.id}

    except IntegrityError:
        return 400, {"detail": f"A product with the name '{payload.name}' already exists in your team."}
    except Exception as e:
        return 400, {"detail": str(e)}


@router.post(
    "/project/",
    response={201: CreateItemResponse, 400: ErrorResponse, 403: ErrorResponse},
)
def create_project(request, payload: CreateProjectRequest):
    """Create a new project."""
    try:
        team_id = get_current_team_id(request)
        if team_id is None:
            return 400, {"detail": "No current team selected"}

        # Verify the product exists and belongs to the team
        try:
            product = Product.objects.get(id=payload.product_id, team_id=team_id)
        except Product.DoesNotExist:
            return 400, {"detail": "Product not found or does not belong to your team"}

        # Create the project
        project = Project.objects.create(name=payload.name, team_id=team_id)

        # Link the project to the product
        product.projects.add(project)

        return 201, {"id": project.id}

    except IntegrityError:
        return 400, {"detail": f"A project with the name '{payload.name}' already exists in your team."}
    except Exception as e:
        return 400, {"detail": str(e)}

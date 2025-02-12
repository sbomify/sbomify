from ninja import Field, Router, Schema
from ninja.security import django_auth

from access_tokens.auth import PersonalAccessTokenAuth
from sboms.models import Component, Product, Project
from sboms.utils import verify_item_access
from teams.models import Team

from .schemas import ErrorResponse


class RenameItemSchema(Schema):
    class Config(Schema.Config):
        str_strip_whitespace = True

    name: str = Field(..., max_length=255, min_length=1)


router = Router(tags=["core"], auth=(PersonalAccessTokenAuth(), django_auth))

item_type_map = {"team": Team, "component": Component, "project": Project, "product": Product}


@router.patch(
    "/rename/{item_type}/{item_id}",
    response={
        204: None,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    }
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

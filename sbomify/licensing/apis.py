from ninja import Router, Schema

from . import ALL_LICENSES, validate_expression

router = Router(tags=["licensing"])


class LicenseExpressionPayload(Schema):
    expression: str


@router.get("/licenses", response=list[dict])
def list_licenses(request):
    return list(ALL_LICENSES.values())


@router.post("/license-expressions/validate", response={200: dict, 400: dict})
def validate_license_expression(request, payload: LicenseExpressionPayload):
    status, data = validate_expression(payload.expression)
    return status, data

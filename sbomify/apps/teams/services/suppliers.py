"""Reading and writing the workspace's supplier list.

A supplier here is a vendor the workspace collects artifacts *from*. See
:class:`~sbomify.apps.teams.models.Supplier` for why that is a separate record
from the supplier named inside an SBOM.

Every function returns a :class:`ServiceResult` so views stay free of the ORM
and of HTTP concerns.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction

from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.teams.models import Supplier, Team


def _first_error(exc: DjangoValidationError) -> str:
    """The first message from a Django ValidationError, field-form or not."""
    if hasattr(exc, "message_dict"):
        for messages in exc.message_dict.values():
            if messages:
                return str(messages[0])
    return str(exc.messages[0]) if exc.messages else "Invalid input"


def list_suppliers(team: Team, search: str = "") -> ServiceResult[list[Supplier]]:
    """The workspace's suppliers, optionally filtered by name or contact."""
    queryset = Supplier.objects.filter(team=team)
    if search := (search or "").strip():
        queryset = queryset.filter(name__icontains=search) | queryset.filter(contact_email__icontains=search)
    return ServiceResult.success(list(queryset.order_by("name")))


def get_supplier(team: Team, supplier_id: str) -> ServiceResult[Supplier]:
    """One supplier, scoped to the workspace.

    Scoped rather than fetched by id alone: an id from another workspace has to
    read as absent, not as forbidden, so the lookup does not confirm it exists.
    """
    supplier = Supplier.objects.filter(team=team, id=supplier_id).first()
    if supplier is None:
        return ServiceResult.failure("Supplier not found", status_code=404)
    return ServiceResult.success(supplier)


def create_supplier(team: Team, data: dict[str, Any]) -> ServiceResult[Supplier]:
    """Add a supplier to the workspace."""
    supplier = Supplier(
        team=team,
        name=data.get("name") or "",
        contact_name=data.get("contact_name") or "",
        contact_email=data.get("contact_email") or "",
        website=data.get("website") or "",
        notes=data.get("notes") or "",
    )
    try:
        # Wrapped so a constraint violation does not poison an enclosing
        # transaction: without the savepoint the request's transaction is
        # unusable after the IntegrityError and every later query fails.
        with transaction.atomic():
            supplier.full_clean()
            supplier.save()
    except DjangoValidationError as e:
        return ServiceResult.failure(_first_error(e), status_code=400)
    except IntegrityError:
        # full_clean catches the case-insensitive clash, so reaching here means
        # a concurrent insert won the race.
        return ServiceResult.failure("A supplier with this name already exists in this workspace", status_code=409)
    return ServiceResult.success(supplier)


def update_supplier(team: Team, supplier_id: str, data: dict[str, Any]) -> ServiceResult[Supplier]:
    """Change a supplier's details. Absent keys are left alone."""
    result = get_supplier(team, supplier_id)
    if not result.ok or result.value is None:
        return result

    supplier = result.value
    for field in ("name", "contact_name", "contact_email", "website", "notes"):
        if field in data:
            setattr(supplier, field, data[field] or "")

    try:
        with transaction.atomic():
            supplier.full_clean()
            supplier.save()
    except DjangoValidationError as e:
        return ServiceResult.failure(_first_error(e), status_code=400)
    except IntegrityError:
        return ServiceResult.failure("A supplier with this name already exists in this workspace", status_code=409)
    return ServiceResult.success(supplier)


def delete_supplier(team: Team, supplier_id: str) -> ServiceResult[None]:
    """Remove a supplier from the workspace."""
    result = get_supplier(team, supplier_id)
    if not result.ok or result.value is None:
        return ServiceResult.failure(result.error or "Supplier not found", status_code=result.status_code or 404)
    result.value.delete()
    return ServiceResult.success(None)

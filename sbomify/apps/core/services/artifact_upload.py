"""Where an upload goes: the components in the current workspace that take an artifact of one kind.

Uploads happen on a component page, in its upload dialog. A workspace-level
"Upload VEX" action therefore has to end on a component, and this service picks
the candidates and builds links that open that component's dialog on load.
"""

from dataclasses import dataclass
from typing import Any

from django.db.models import Exists, OuterRef
from django.http import HttpRequest
from django.urls import reverse

from sbomify.apps.core.authz import can
from sbomify.apps.core.models import Component
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Workspace

FORBIDDEN_MESSAGE = "You can't upload artifacts in this workspace."


@dataclass(frozen=True)
class UploadKind:
    component_type: str
    fragment: str
    label: str
    subtitle: str
    empty_message: str
    needs_sbom: bool = False


# The fragment is what the component page's upload dialog reads on load.
UPLOAD_KINDS: dict[str, UploadKind] = {
    "sbom": UploadKind(
        component_type=Component.ComponentType.BOM,
        fragment="upload-sbom",
        label="SBOM",
        subtitle="Choose the component this SBOM is for.",
        empty_message="An SBOM belongs to a component. Create one, then upload it.",
    ),
    "cbom": UploadKind(
        component_type=Component.ComponentType.BOM,
        fragment="upload-cbom",
        label="CBOM",
        subtitle="Choose the component this CBOM is for.",
        empty_message="A CBOM belongs to a component. Create one, then upload it.",
        needs_sbom=True,
    ),
    "vex": UploadKind(
        component_type=Component.ComponentType.BOM,
        fragment="upload-vex",
        label="VEX",
        subtitle="Choose the component this VEX is for.",
        empty_message="A VEX belongs to a component. Create one, then upload it.",
        needs_sbom=True,
    ),
    "document": UploadKind(
        component_type=Component.ComponentType.DOCUMENT,
        fragment="upload-artifact",
        label="document",
        subtitle="Choose the document component this file is for.",
        empty_message="Documents belong to a document component. Create one, then upload.",
    ),
}


def _can_upload(request: HttpRequest, kind: str, workspace: Workspace) -> bool:
    # component:manage is what renders the uploader on the component page, and
    # artifact:publish is what the upload API checks: a link needs both or it
    # dead-ends. A VEX file also needs the triage capability.
    actions = ["component:manage", "artifact:publish"]
    if kind == "vex":
        actions.append("artifact:publish_vex")
    return all(can(request, action, workspace) for action in actions)


def upload_targets(request: HttpRequest, kind: str) -> ServiceResult[dict[str, Any]]:
    upload_kind = UPLOAD_KINDS.get(kind)
    if upload_kind is None:
        return ServiceResult.failure("Unknown artifact type.", status_code=404)

    workspace_key = (request.session.get("current_workspace") or {}).get("key")
    workspace = Workspace.objects.filter(key=workspace_key).first() if workspace_key else None
    if workspace is None or not _can_upload(request, kind, workspace):
        return ServiceResult.failure(FORBIDDEN_MESSAGE, status_code=403)

    ordering = ("-has_sbom", "name", "id") if upload_kind.needs_sbom else ("name", "id")
    components = (
        Component.objects.filter(team=workspace, component_type=upload_kind.component_type)
        .annotate(
            has_sbom=Exists(SBOM.objects.filter(component=OuterRef("pk"), bom_type=SBOM.BomType.SBOM)),
        )
        .prefetch_related("products")
        .order_by(*ordering)
    )
    rows = [
        {
            "id": component.id,
            "name": component.name,
            "products": sorted(product.name for product in component.products.all()),
            "has_sbom": component.has_sbom,
            "url": f"{reverse('core:component_details', args=[component.id])}#{upload_kind.fragment}",
        }
        for component in components
    ]
    return ServiceResult.success(
        {
            "kind": kind,
            "label": upload_kind.label,
            "subtitle": upload_kind.subtitle,
            "empty_message": upload_kind.empty_message,
            "needs_sbom": upload_kind.needs_sbom,
            "new_component_url": f"{reverse('core:component_new')}?type={upload_kind.component_type}",
            "rows": rows,
        }
    )

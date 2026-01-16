from __future__ import annotations

from typing import Optional

from sbomify.apps.sboms.models import SBOM


def get_latest_sbom_id_for_component(component_id: str) -> Optional[str]:
    return SBOM.objects.filter(component_id=component_id).order_by("-created_at").values_list("id", flat=True).first()

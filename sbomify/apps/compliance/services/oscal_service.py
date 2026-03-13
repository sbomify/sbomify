"""OSCAL catalog and assessment service — load, import, assess, serialize."""

from __future__ import annotations

import functools
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trestle.oscal.assessment_results import AssessmentResults, ImportAp, Result
from trestle.oscal.catalog import Catalog
from trestle.oscal.common import (
    ControlSelection,
    Finding,
    FindingTarget,
    FindingTargetTypeValidValues,
    IncludeAll,
    Metadata,
    ObjectiveStatus,
    ObjectiveStatusStateValidValues,
    Property,
    ReviewedControls,
)

from sbomify.apps.compliance.models import (
    OSCALAssessmentResult,
    OSCALCatalog,
    OSCALControl,
    OSCALFinding,
)

if TYPE_CHECKING:
    from sbomify.apps.core.models import Product, User
    from sbomify.apps.teams.models import Team

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "oscal_data" / "cra-annex-i-catalog.json"

_CRA_CATALOG_NAME = "EU CRA Annex I"
_CRA_CATALOG_VERSION = "1.0.0"


@functools.cache
def load_cra_catalog() -> Catalog:
    """Load and validate the static CRA catalog JSON via trestle.

    Uses ``functools.cache`` for singleton behavior so the file is read
    and parsed only once per process.
    """
    raw = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    return Catalog(**raw["catalog"])


def import_catalog_to_db(trestle_catalog: Catalog, name: str, version: str) -> OSCALCatalog:
    """Create an ``OSCALCatalog`` record and materialize ``OSCALControl`` rows.

    Iterates through all catalog groups and their controls to create
    individual control rows for efficient querying.
    """
    from django.db import transaction

    with transaction.atomic():
        catalog_json = json.loads(trestle_catalog.oscal_serialize_json())
        db_catalog = OSCALCatalog.objects.create(
            name=name,
            version=version,
            source_url="https://eur-lex.europa.eu/eli/reg/2024/2847/oj/eng",
            catalog_json=catalog_json,
        )

        sort_order = 0
        controls_to_create: list[OSCALControl] = []
        for group in trestle_catalog.groups or []:
            group_id = group.id or ""
            group_title = group.title
            for control in group.controls or []:
                # Extract the prose from the statement part as the description
                description = ""
                for part in control.parts or []:
                    if part.name == "statement" and part.prose:
                        description = part.prose
                        break
                controls_to_create.append(
                    OSCALControl(
                        catalog=db_catalog,
                        control_id=control.id,
                        group_id=group_id,
                        group_title=group_title,
                        title=control.title,
                        description=description,
                        sort_order=sort_order,
                    )
                )
                sort_order += 1

        OSCALControl.objects.bulk_create(controls_to_create)
    return db_catalog


def ensure_cra_catalog() -> OSCALCatalog:
    """Get-or-create the CRA catalog and its controls in the database.

    Idempotent: if a catalog with the matching name and version already
    exists, it is returned without modification.
    """
    try:
        return OSCALCatalog.objects.get(name=_CRA_CATALOG_NAME, version=_CRA_CATALOG_VERSION)
    except OSCALCatalog.DoesNotExist:
        trestle_catalog = load_cra_catalog()
        return import_catalog_to_db(trestle_catalog, _CRA_CATALOG_NAME, _CRA_CATALOG_VERSION)


def create_assessment_result(
    catalog: OSCALCatalog,
    team: Team,
    product: Product,
    user: User,
) -> OSCALAssessmentResult:
    """Create an ``OSCALAssessmentResult`` and bulk-create 21 unanswered ``OSCALFinding`` rows."""
    ar = OSCALAssessmentResult.objects.create(
        catalog=catalog,
        team=team,
        title=f"CRA Assessment — {product.name}",
        description=f"CRA Annex I compliance assessment for product {product.name}",
        assessor=getattr(user, "get_full_name", lambda: str(user))(),
        created_by=user,
    )

    controls = OSCALControl.objects.filter(catalog=catalog).order_by("sort_order")
    findings = [
        OSCALFinding(
            assessment_result=ar,
            control=control,
            status=OSCALFinding.FindingStatus.UNANSWERED,
        )
        for control in controls
    ]
    OSCALFinding.objects.bulk_create(findings)
    return ar


def update_finding(finding: OSCALFinding, status: str, notes: str = "") -> OSCALFinding:
    """Update a finding's status and notes.

    Raises ``ValueError`` if *status* is not a valid ``FindingStatus`` choice.
    """
    valid_statuses = {choice[0] for choice in OSCALFinding.FindingStatus.choices}
    if status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {sorted(valid_statuses)}")

    finding.status = status
    finding.notes = notes
    finding.save(update_fields=["status", "notes", "updated_at"])
    return finding


def get_annex_reference(catalog_json: dict[str, Any], control_id: str) -> str:
    """Look up the annex reference for a control from catalog JSON."""
    for group in catalog_json.get("groups", []):
        for ctrl in group.get("controls", []):
            if ctrl.get("id") == control_id:
                for prop in ctrl.get("props", []):
                    if prop.get("name") == "annex-ref":
                        return str(prop.get("value", ""))
                return ""
    return ""


# ---------------------------------------------------------------------------
# OSCAL serialization helpers
# ---------------------------------------------------------------------------

_STATUS_MAP: dict[str, ObjectiveStatusStateValidValues] = {
    "satisfied": ObjectiveStatusStateValidValues.satisfied,
    "not-satisfied": ObjectiveStatusStateValidValues.not_satisfied,
    "not-applicable": ObjectiveStatusStateValidValues.satisfied,  # satisfied + prop
    "unanswered": ObjectiveStatusStateValidValues.not_satisfied,  # mapped to not-satisfied, marked omitted via prop
}


def _build_finding(db_finding: OSCALFinding) -> Finding:
    """Convert a DB finding to a trestle OSCAL Finding."""
    status_str = db_finding.status
    state = _STATUS_MAP.get(status_str, ObjectiveStatusStateValidValues.not_satisfied)

    props: list[Property] = []
    if status_str == "not-applicable":
        props.append(Property(name="finding-disposition", value="not-applicable"))
    elif status_str == "unanswered":
        props.append(Property(name="finding-disposition", value="omitted"))

    target = FindingTarget(
        type=FindingTargetTypeValidValues.objective_id,
        target_id=db_finding.control.control_id,
        status=ObjectiveStatus(state=state),
    )

    return Finding(
        uuid=str(uuid.uuid4()),
        title=db_finding.control.title,
        description=db_finding.notes or f"Assessment of {db_finding.control.control_id}",
        target=target,
        props=props if props else None,
        remarks=db_finding.notes if db_finding.notes else None,
    )


def build_trestle_assessment_results(ar: OSCALAssessmentResult) -> AssessmentResults:
    """Build a trestle OSCAL ``AssessmentResults`` object from DB models.

    Status mapping:
    - satisfied -> satisfied
    - not-satisfied -> not-satisfied
    - not-applicable -> satisfied + ``finding-disposition=not-applicable`` prop
    - unanswered -> not-satisfied + ``finding-disposition=omitted`` prop
    """
    findings_qs = ar.findings.select_related("control").order_by("control__sort_order")
    trestle_findings = [_build_finding(f) for f in findings_qs]

    # Build control selections — include all controls from the catalog
    control_selections = [
        ControlSelection(include_all=IncludeAll()),
    ]

    now = datetime.now(tz=timezone.utc)
    metadata = Metadata(
        title=ar.title,
        last_modified=now,
        version="1.0.0",
        oscal_version="1.1.2",
    )

    result = Result(
        uuid=str(uuid.uuid4()),
        title=ar.title,
        description=ar.description or "CRA Annex I compliance assessment",
        start=ar.started_at,
        end=ar.completed_at,
        reviewed_controls=ReviewedControls(control_selections=control_selections),
        findings=trestle_findings if trestle_findings else None,
    )

    return AssessmentResults(
        uuid=str(uuid.uuid4()),
        metadata=metadata,
        import_ap=ImportAp(href="#"),
        results=[result],
    )


def serialize_assessment_results(ar: OSCALAssessmentResult) -> str:
    """Build and serialize an ``AssessmentResults`` to a JSON string."""
    trestle_ar = build_trestle_assessment_results(ar)
    result: str = trestle_ar.oscal_serialize_json()
    return result

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
    CRAAssessment,
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
_CRA_CATALOG_VERSION = "1.1.0"


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
                # Extract annex-part prop to determine Part I/II and mandatory status.
                # Fail closed on unknown values — a typo like ``"part-iii"``
                # in the catalog JSON would otherwise bypass ``choices``
                # validation (``bulk_create`` does not run ``full_clean``)
                # and land as Part I with ``is_mandatory=False``,
                # silently downgrading a vulnerability-handling control.
                annex_part = "part-i"
                for prop in control.props or []:
                    if prop.name == "annex-part":
                        annex_part = prop.value
                        break
                if annex_part not in {"part-i", "part-ii"}:
                    raise ValueError(
                        f"Control {control.id!r} in catalog {db_catalog.name!r} has an "
                        f"unrecognised ``annex-part`` prop: {annex_part!r}. "
                        f"Only 'part-i' and 'part-ii' are valid (CRA Annex I)."
                    )
                # Part II (vulnerability handling) is always mandatory (CRA Art 13(4), FAQ 4.1.3)
                is_mandatory = annex_part == "part-ii"

                controls_to_create.append(
                    OSCALControl(
                        catalog=db_catalog,
                        control_id=control.id,
                        group_id=group_id,
                        group_title=group_title,
                        title=control.title,
                        description=description,
                        is_mandatory=is_mandatory,
                        annex_part=annex_part,
                        sort_order=sort_order,
                    )
                )
                sort_order += 1

        OSCALControl.objects.bulk_create(controls_to_create)
    return db_catalog


def ensure_cra_catalog() -> OSCALCatalog:
    """Get-or-create the CRA catalog and its controls in the database.

    Idempotent: if a catalog with the matching name and version already
    exists, it is returned without modification.  Handles concurrent
    creation by catching ``IntegrityError`` and re-fetching.
    """
    from django.db import IntegrityError

    try:
        return OSCALCatalog.objects.get(name=_CRA_CATALOG_NAME, version=_CRA_CATALOG_VERSION)
    except OSCALCatalog.DoesNotExist:
        try:
            trestle_catalog = load_cra_catalog()
            return import_catalog_to_db(trestle_catalog, _CRA_CATALOG_NAME, _CRA_CATALOG_VERSION)
        except IntegrityError:
            return OSCALCatalog.objects.get(name=_CRA_CATALOG_NAME, version=_CRA_CATALOG_VERSION)


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


def update_finding(
    finding: OSCALFinding,
    status: str,
    notes: str = "",
    justification: str = "",
    *,
    actor: Any = None,
) -> OSCALFinding:
    """Update a finding's status, notes, and justification.

    Raises ``ValueError`` if *status* is not a valid ``FindingStatus`` choice.
    Raises ``ValueError`` if a Part II control is set to not-applicable (CRA Art 13(4)).
    Raises ``ValueError`` if a Part I control is set to not-applicable without justification.

    ``actor`` is the ``User`` performing the change — recorded in the
    audit log for CRA non-repudiation. The parameter is keyword-only so
    existing call sites (tests, migration helpers) that don't carry a
    user context continue to work; production callers from the API
    layer pass ``request.user``.
    """
    # Coerce to strings to guard against None from upstream callers
    notes = str(notes) if notes else ""
    justification = str(justification) if justification else ""

    valid_statuses = {choice[0] for choice in OSCALFinding.FindingStatus.choices}
    if status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {sorted(valid_statuses)}")

    # Part II controls (vulnerability handling) are always mandatory — cannot be N/A
    # CRA Art 13(4), FAQ 4.1.3
    if status == "not-applicable" and finding.control.is_mandatory:
        raise ValueError(
            f"Control {finding.control.control_id} is a Part II (vulnerability handling) requirement "
            f"and is always mandatory (CRA Art 13(4)). It cannot be marked as not-applicable."
        )

    # Part I controls marked N/A require a clear justification (CRA Art 13(4))
    if status == "not-applicable" and not finding.control.is_mandatory and not justification.strip():
        raise ValueError(
            f"Control {finding.control.control_id} requires a clear justification when marked "
            f"not-applicable (CRA Art 13(4))."
        )

    # Clear the justification when leaving the not-applicable state. A stale
    # justification lingering on a satisfied / not-satisfied / unanswered
    # finding would render misleadingly in the risk-assessment export and the
    # technical-documentation package (CRA Annex VII) — the audit-delta row
    # captures the implicit clear so the transition is still traceable.
    if status != "not-applicable":
        justification = ""

    before = {"status": finding.status, "notes": finding.notes, "justification": finding.justification}
    finding.status = status
    finding.notes = notes
    finding.justification = justification
    finding.save(update_fields=["status", "notes", "justification", "updated_at"])

    from sbomify.apps.compliance.audit import log_finding_update

    # Use the CRAAssessment PK (not the OSCALAssessmentResult PK) so
    # audit events across event types (``cra.assessment.step_save`` and
    # ``cra.finding.update``) share the same ``assessment_id`` key for
    # downstream correlation. The OSCAL AR is an implementation detail
    # of the assessment; operators + regulators reason about the
    # CRAAssessment.
    try:
        cra_assessment_id: str | None = str(finding.assessment_result.cra_assessment.pk)
    except CRAAssessment.DoesNotExist:
        cra_assessment_id = None

    log_finding_update(
        user=actor,
        assessment_id=cra_assessment_id,
        finding_id=str(finding.pk),
        control_id=finding.control.control_id,
        before=before,
        after={"status": status, "notes": notes, "justification": justification},
    )
    return finding


def get_annex_reference(catalog_json: dict[str, Any], control_id: str) -> str:
    """Look up the annex reference for a control from catalog JSON.

    Handles both raw catalog dicts and trestle-serialized dicts
    where the payload is wrapped under a ``"catalog"`` key.
    """
    inner = catalog_json.get("catalog", catalog_json)
    for group in inner.get("groups", []):
        for ctrl in group.get("controls", []):
            if ctrl.get("id") == control_id:
                for prop in ctrl.get("props", []):
                    if prop.get("name") == "annex-ref":
                        return str(prop.get("value", ""))
                return ""
    return ""


CRA_EURLEX_HTML = "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ:L_202402847"

# Anchors extracted from the actual EUR-Lex HTML page
_CRA_ANNEX_ANCHORS = {
    "Part I": "d1e47-68-1",  # Part I: Cybersecurity requirements
    "Part II": "d1e143-68-1",  # Part II: Vulnerability handling requirements
}


def get_annex_url(annex_reference: str) -> str:
    """Build a EUR-Lex URL for the given annex reference.

    Links to the exact Part I or Part II section of Annex I in the official
    EU CRA text on EUR-Lex. Defense-in-depth: only emit https URLs so a future
    change to ``CRA_EURLEX_HTML`` that accidentally drops the scheme cannot
    surface a ``javascript:`` URL to the Alpine ``:href`` binding on Step 3.
    """
    if not annex_reference:
        return ""
    for part, anchor in _CRA_ANNEX_ANCHORS.items():
        if part in annex_reference:
            url = f"{CRA_EURLEX_HTML}#{anchor}"
            break
    else:
        url = f"{CRA_EURLEX_HTML}#anx_I"
    return url if url.startswith("https://") else ""


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

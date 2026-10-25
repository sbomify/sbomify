"""Changes an AI agent asks to make to a published advisory, held for a person.

An agent token may draft an advisory and keep editing the draft: nothing in a
draft reaches anyone until a person publishes it, and publishing is the review.
A published advisory is different. Its timeline, fields and product statuses
are what the Trust Center shows and the CSAF document carries, so an agent's
write to one would go out under the workspace's name with nobody having read
it. Here such a write becomes an :class:`AdvisoryProposal` instead.

Every kind of write an agent can make to an advisory has a proposal kind, so
the gate has no gaps: a new update, an edit to an earlier update, an edit to
the advisory's own fields, a product status change, and a product added.
Approving one runs the same service function a person's direct edit runs, so
there is still one implementation of each write and of the rules it enforces.
The events it writes are attributed to the agent's token and carry who
approved it, so the timeline says both.

What makes a proposal readable is the diff. Each one keeps the values it
would replace as they were when it was sent (``baseline``), and the review
shows those against what it proposes, plus a warning when someone has changed
the same thing since.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from sbomify.apps.core.models import Product, Release
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.security_advisories.models import (
    AdvisoryProductStatus,
    AdvisoryProposal,
    SecurityAdvisory,
    Severity,
)
from sbomify.apps.security_advisories.services import advisories as advisory_service
from sbomify.apps.security_advisories.services.advisories import (
    PRODUCT_STATUS_FIELDS,
    REMEDIATION_META,
    display_date,
)

Kind = AdvisoryProposal.Kind

# The advisory fields an edit proposal may carry, and how the review names them.
ADVISORY_FIELDS: dict[str, str] = {
    "title": "Title",
    "summary": "Summary",
    "description": "Description",
    "severity": "Severity",
    "cvss": "CVSS",
}

EDITABLE_ADVISORY_FIELDS = frozenset({"title", "summary", "description", "severity", "cvss_score", "cvss_vector"})

STATUS_FIELD_LABELS: dict[str, str] = {
    "status": "Status",
    "justification": "Why it is not affected",
    "response": "Response",
    "impact_statement": "Impact",
    "action_statement": "What users should do",
    "recommended_version": "Recommended version",
    "recommended_release_id": "Recommended release",
    "fixed_version": "Fixed in",
    "fixed_release_id": "Fixed in release",
}

KIND_META: dict[str, dict[str, str]] = {
    Kind.POST_UPDATE: {"label": "New update", "icon": "fas fa-comment-dots"},
    Kind.EDIT_UPDATE: {"label": "Edit to an update", "icon": "fas fa-pen"},
    Kind.EDIT_ADVISORY: {"label": "Edit to the advisory", "icon": "fas fa-file-pen"},
    Kind.PRODUCT_STATUS: {"label": "Product status", "icon": "fas fa-cube"},
    Kind.ADD_PRODUCT: {"label": "Product added", "icon": "fas fa-cubes"},
}

OUTCOME_VARIANTS: dict[str, str] = {
    AdvisoryProposal.Status.PENDING: "warning",
    AdvisoryProposal.Status.APPROVED: "success",
    AdvisoryProposal.Status.REJECTED: "danger",
    AdvisoryProposal.Status.SUPERSEDED: "secondary",
}

# Past this, decided proposals fold into the history count.
RECENT_DECIDED = 10

# Above this many characters a value is long text, which the review shows as
# a block rather than inline.
_LONG_VALUE = 80


def _field_key(field: str) -> str:
    """The reviewed field a payload key belongs to: score and vector are one CVSS."""
    return "cvss" if field.startswith("cvss") else field


def _listed(words: list[str]) -> str:
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def needs_approval(advisory: SecurityAdvisory, channel: str) -> bool:
    """Whether a write from ``channel`` to ``advisory`` must wait for a person.

    Only an AI agent's, and only once the advisory has been published: a draft
    is the agent's to shape, since publishing it is the approval.
    """
    return channel == "agent" and advisory.status != SecurityAdvisory.Status.DRAFT


def find_advisory(team: Any, advisory_id: str) -> SecurityAdvisory | None:
    return SecurityAdvisory.objects.filter(team=team).filter(Q(id=advisory_id) | Q(tracking_id=advisory_id)).first()


class _Invalid(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _choice_label(choices: Any, value: Any) -> str:
    if not value:
        return ""
    try:
        return str(choices(value).label)
    except ValueError:
        return str(value)


def _release_label(release_id: Any) -> str:
    if not release_id:
        return ""
    release = Release.objects.filter(pk=release_id).first()
    return release.name if release else str(release_id)


def _status_value_label(field: str, value: Any) -> str:
    if field == "status":
        return _choice_label(AdvisoryProductStatus.Status, value)
    if field == "justification":
        return _choice_label(AdvisoryProductStatus.Justification, value)
    if field == "response":
        return _choice_label(AdvisoryProductStatus.Response, value)
    if field in ("fixed_release_id", "recommended_release_id"):
        return _release_label(value)
    return str(value or "")


def _cvss_text(score: Any, vector: Any) -> str:
    if score in (None, ""):
        return ""
    return f"{score} ({vector})" if vector else str(score)


def _advisory_values(advisory_id: str, team: Any) -> dict[str, str]:
    """The advisory's own fields as an edit proposal compares them."""
    projection = advisory_service.get_advisory(team, advisory_id).value or {}
    return {
        "title": projection.get("title", ""),
        "summary": projection.get("summary", ""),
        "description": projection.get("description", ""),
        "severity": projection.get("severity", ""),
        "cvss": _cvss_text(projection.get("cvss_score"), projection.get("cvss_vector", "")),
    }


def _status_link(advisory: SecurityAdvisory, payload: dict[str, Any]) -> tuple[list[AdvisoryProductStatus], str]:
    """The rows a product status proposal edits, and the product's name."""
    rows = AdvisoryProductStatus.objects.select_related(
        "vulnerability", "advisory_product__product", "advisory_component__component"
    ).filter(vulnerability__advisory=advisory)
    if status_id := payload.get("status_id"):
        rows = rows.filter(pk=status_id)
    else:
        product_id = payload.get("product_id", "")
        link = advisory.products.filter(Q(product_id=product_id) | Q(id=product_id)).first()
        if link is None:
            raise _Invalid("This advisory does not name that product.", 404)
        rows = rows.filter(advisory_product=link)
        if vulnerability_id := payload.get("vulnerability_id"):
            rows = rows.filter(vulnerability_id=vulnerability_id)
    found = list(rows.order_by("created_at"))
    if not found:
        raise _Invalid("Product status not found", 404)
    return found, advisory_service.status_subject(found[0])


def _status_values(row: AdvisoryProductStatus) -> dict[str, str]:
    snapshot = advisory_service._status_snapshot(row)
    snapshot["fixed_release_id"] = ""
    snapshot["recommended_release_id"] = row.recommended_release.name if row.recommended_release else ""
    return snapshot


def _prepared(team: Any, advisory: SecurityAdvisory, kind: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Check a proposal before it is queued, returning its target and baseline.

    The checks are the ones the agent can act on now: an unknown field, an
    update that does not exist, a note left blank. Everything else, the
    publication rules included, is left to the write itself at approval,
    which is where the advisory's state at that moment is known.
    """
    if kind == Kind.POST_UPDATE:
        update_kind = (payload.get("kind") or "").strip()
        note = (payload.get("note") or "").strip()
        if update_kind == "update":
            if not note:
                raise _Invalid("An update needs a note.")
        elif update_kind not in SecurityAdvisory.RemediationStatus.values:
            raise _Invalid("Unknown update type.")
        elif update_kind == advisory.remediation_status:
            label = REMEDIATION_META.get(update_kind, {}).get("label", update_kind)
            raise _Invalid(f"The advisory is already {label}.")
        return "", {"remediation_status": advisory.remediation_status}

    if kind == Kind.EDIT_UPDATE:
        event, current = advisory_service.current_message(advisory, payload.get("event_id", ""))
        if event is None:
            raise _Invalid("Update not found", 404)
        note = (payload.get("note") or "").strip()
        if not note:
            raise _Invalid("An update needs a note.")
        if note == current:
            raise _Invalid("That is what the update already says.")
        return f"event:{event.id}", {"note": current, "event_kind": event.event_type}

    if kind == Kind.EDIT_ADVISORY:
        fields = payload.get("fields") or {}
        if not fields:
            raise _Invalid("Nothing to change.")
        if unknown := sorted(set(fields) - EDITABLE_ADVISORY_FIELDS):
            raise _Invalid(f"Unknown field: {', '.join(unknown)}.")
        if "title" in fields and not str(fields["title"] or "").strip():
            raise _Invalid("An advisory needs a title.")
        if (severity := fields.get("severity")) and severity not in Severity.values:
            raise _Invalid("Unknown severity.")
        values = _advisory_values(advisory.id, team)
        keys = sorted({_field_key(key) for key in fields})
        return "fields:" + ",".join(keys), {key: values[key] for key in keys}

    if kind == Kind.PRODUCT_STATUS:
        changes = payload.get("changes") or {}
        if not changes:
            raise _Invalid("Nothing to change.")
        if unknown := sorted(set(changes) - PRODUCT_STATUS_FIELDS):
            raise _Invalid(f"Unknown field: {', '.join(unknown)}.")
        rows, subject = _status_link(advisory, payload)
        values = _status_values(rows[0])
        target = (
            f"status:{payload['status_id']}"
            if payload.get("status_id")
            else (f"product:{payload.get('product_id')}:{payload.get('vulnerability_id') or ''}")
        )
        return target, {"subject": subject, "rows": len(rows), **{key: values.get(key, "") for key in changes}}

    if kind == Kind.ADD_PRODUCT:
        product = Product.objects.filter(id=payload.get("product_id", ""), team=team).first()
        if product is None:
            raise _Invalid("Product not found", 404)
        if unknown := sorted(set(payload.get("changes") or {}) - PRODUCT_STATUS_FIELDS):
            raise _Invalid(f"Unknown field: {', '.join(unknown)}.")
        release_ids = list(dict.fromkeys(payload.get("release_ids") or []))
        if Release.objects.filter(id__in=release_ids, product=product).count() != len(release_ids):
            raise _Invalid("Release not found", 404)
        listed = advisory.products.filter(product=product).exists()
        return f"add:{product.id}", {"product": product.name, "listed": listed}

    raise _Invalid("Unknown change.")


@transaction.atomic
def submit_proposal(
    team: Any,
    user: Any,
    advisory_id: str,
    *,
    kind: str,
    payload: dict[str, Any],
    context: str = "",
    via: dict[str, str] | None = None,
    token: Any = None,
) -> ServiceResult[AdvisoryProposal]:
    """Queue a change for review instead of applying it.

    A pending proposal from the same token that changes the same thing (the
    same update, product or set of fields) is replaced: an agent that runs on
    a schedule resubmits, and a reviewer should read its latest answer once.
    """
    advisory = advisory_service._locked_advisory(team, advisory_id)
    if advisory is None:
        return ServiceResult.failure("Advisory not found", status_code=404)
    if advisory.status == SecurityAdvisory.Status.WITHDRAWN:
        return ServiceResult.failure("This advisory has been withdrawn, so it is final.", status_code=409)
    try:
        target, baseline = _prepared(team, advisory, kind, payload)
    except _Invalid as invalid:
        return ServiceResult.failure(invalid.message, status_code=invalid.status_code)

    via = via or {}
    if target:
        same_sender = Q(submitted_token=token) if token is not None else Q(submitted_by=user, submitted_token=None)
        advisory.proposals.filter(same_sender, kind=kind, target=target, status=AdvisoryProposal.Status.PENDING).update(
            status=AdvisoryProposal.Status.SUPERSEDED, decided_at=timezone.now()
        )

    proposal = AdvisoryProposal.objects.create(
        team=team,
        advisory=advisory,
        kind=kind,
        target=target,
        payload=payload,
        baseline=baseline,
        context=(context or "").strip(),
        channel=via.get("channel", "agent"),
        submitted_by=user,
        submitted_token=token,
        submitted_token_description=getattr(token, "description", "") or "",
    )
    advisory_service._announce(team, advisory.id, "proposed")
    return ServiceResult.success(proposal)


def _apply(team: Any, proposal: AdvisoryProposal, via: dict[str, str]) -> ServiceResult[str]:
    """Run the write the proposal holds, through the service a person's edit uses."""
    advisory_id = proposal.advisory_id
    actor = proposal.submitted_by
    payload = proposal.payload or {}

    if proposal.kind == Kind.POST_UPDATE:
        return advisory_service.post_update(
            team, actor, advisory_id, kind=payload.get("kind", ""), note=payload.get("note", ""), via=via
        )
    if proposal.kind == Kind.EDIT_UPDATE:
        return advisory_service.edit_message(
            team, actor, advisory_id, payload.get("event_id", ""), note=payload.get("note", ""), via=via
        )
    if proposal.kind == Kind.EDIT_ADVISORY:
        fields = payload.get("fields") or {}
        stored = advisory_service.get_advisory(team, advisory_id).value or {}
        cvss_score = cvss_vector = None
        if "cvss_score" in fields or "cvss_vector" in fields:
            score = fields.get("cvss_score", stored.get("cvss_score"))
            cvss_score = "" if score is None else str(score)
            if "cvss_vector" in fields:
                cvss_vector = fields["cvss_vector"] or ""
            else:
                cvss_vector = (stored.get("cvss_vector") or "") if score is not None else ""
        return advisory_service.update_advisory(
            team,
            actor,
            advisory_id,
            title=fields.get("title") or stored.get("title", ""),
            severity=(fields["severity"] or "") if "severity" in fields else None,
            description=(fields["description"] or "") if "description" in fields else stored.get("description", ""),
            summary=(fields["summary"] or "") if "summary" in fields else None,
            cvss_score=cvss_score,
            cvss_vector=cvss_vector,
            via=via,
        )
    if proposal.kind == Kind.PRODUCT_STATUS:
        changes = payload.get("changes") or {}
        if status_id := payload.get("status_id"):
            return advisory_service.update_product_status(team, actor, advisory_id, status_id, changes=changes, via=via)
        return advisory_service.update_product_statuses(
            team,
            actor,
            advisory_id,
            payload.get("product_id", ""),
            changes=changes,
            vulnerability_id=payload.get("vulnerability_id") or None,
            via=via,
        )
    if proposal.kind == Kind.ADD_PRODUCT:
        product = Product.objects.filter(id=payload.get("product_id", ""), team=team).first()
        if product is None:
            return ServiceResult.failure("The product has been deleted since this was sent.", status_code=409)
        releases = list(Release.objects.filter(id__in=payload.get("release_ids") or [], product=product))
        return advisory_service.add_advisory_product(
            team,
            actor,
            advisory_id,
            product=product,
            affected_releases=releases,
            changes=payload.get("changes") or {},
            via=via,
        )
    return ServiceResult.failure("Unknown change.", status_code=400)


def _locked_pending(team: Any, advisory_id: str, proposal_id: str) -> AdvisoryProposal | ServiceResult[Any]:
    advisory = find_advisory(team, advisory_id)
    proposal = (
        AdvisoryProposal.objects.select_for_update(of=("self",))
        .filter(team=team, advisory=advisory, pk=proposal_id)
        .select_related("submitted_by", "submitted_token")
        .first()
        if advisory is not None
        else None
    )
    if proposal is None:
        return ServiceResult.failure("Proposed change not found", status_code=404)
    if proposal.status != AdvisoryProposal.Status.PENDING:
        return ServiceResult.failure(
            f"This change has already been decided: {proposal.get_status_display().lower()}.", status_code=409
        )
    return proposal


@transaction.atomic
def approve_proposal(
    team: Any, user: Any, advisory_id: str, proposal_id: str, *, note: str | None = None, decision_note: str = ""
) -> ServiceResult[AdvisoryProposal]:
    """Apply a proposed change, optionally with the reviewer's own wording.

    ``note`` replaces the proposed text of a new or edited update, so a
    reviewer can fix a sentence instead of rejecting the whole change. If the
    write is refused, say because the advisory has moved on since, the
    proposal stays pending with nothing applied, and the reason comes back.
    """
    found = _locked_pending(team, advisory_id, proposal_id)
    if isinstance(found, ServiceResult):
        return found
    proposal = found

    revised = False
    if note is not None and proposal.kind in (Kind.POST_UPDATE, Kind.EDIT_UPDATE):
        note = note.strip()
        if note != (proposal.payload.get("note") or "").strip():
            proposal.payload = {**proposal.payload, "note": note, "proposed_note": proposal.payload.get("note", "")}
            revised = True

    via = {
        "channel": proposal.channel,
        "token_id": str(proposal.submitted_token_id or ""),
        "proposal_id": proposal.id,
        "approved_by": advisory_service._actor_name(user),
    }
    with transaction.atomic():
        applied = _apply(team, proposal, via)
        if not applied.ok:
            transaction.set_rollback(True)
    if not applied.ok:
        return ServiceResult.failure(applied.error or "Change not applied.", status_code=applied.status_code or 400)

    proposal.status = AdvisoryProposal.Status.APPROVED
    proposal.decided_by = user
    proposal.decided_at = timezone.now()
    proposal.decision_note = (decision_note or "").strip()
    proposal.revised = revised
    proposal.save(update_fields=["payload", "status", "decided_by", "decided_at", "decision_note", "revised"])
    advisory_service._announce(team, proposal.advisory_id, "proposal_decided")
    return ServiceResult.success(proposal)


@transaction.atomic
def reject_proposal(
    team: Any, user: Any, advisory_id: str, proposal_id: str, *, decision_note: str = ""
) -> ServiceResult[AdvisoryProposal]:
    """Turn a proposed change down. Nothing on the advisory changes."""
    found = _locked_pending(team, advisory_id, proposal_id)
    if isinstance(found, ServiceResult):
        return found
    proposal = found
    proposal.status = AdvisoryProposal.Status.REJECTED
    proposal.decided_by = user
    proposal.decided_at = timezone.now()
    proposal.decision_note = (decision_note or "").strip()
    proposal.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
    advisory_service._announce(team, proposal.advisory_id, "proposal_decided")
    return ServiceResult.success(proposal)


def _person(user: Any) -> str:
    if user is None:
        return "A former member"
    return str(user.get_full_name() or user.email or user.username)


def _change(label: str, before: Any, after: Any) -> dict[str, Any]:
    before, after = str(before or ""), str(after or "")
    return {
        "label": label,
        "before": before,
        "after": after,
        "long": len(before) > _LONG_VALUE or len(after) > _LONG_VALUE or "\n" in before + after,
    }


def _changes(proposal: AdvisoryProposal, baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """Each value the proposal changes, before and after, worded for a reader."""
    payload = proposal.payload or {}
    if proposal.kind == Kind.EDIT_UPDATE:
        return [_change("Update", baseline.get("note"), payload.get("note"))]
    if proposal.kind == Kind.EDIT_ADVISORY:
        fields = payload.get("fields") or {}
        rows = []
        for key, label in ADVISORY_FIELDS.items():
            if key == "cvss":
                if "cvss_score" in fields or "cvss_vector" in fields:
                    rows.append(
                        _change(
                            label, baseline.get("cvss"), _cvss_text(fields.get("cvss_score"), fields.get("cvss_vector"))
                        )
                    )
            elif key in fields:
                after = fields[key]
                if key == "severity":
                    after = str(after or "").title()
                    rows.append(_change(label, str(baseline.get(key) or "").title(), after))
                else:
                    rows.append(_change(label, baseline.get(key), after))
        return rows
    if proposal.kind in (Kind.PRODUCT_STATUS, Kind.ADD_PRODUCT):
        changes = payload.get("changes") or {}
        return [
            _change(STATUS_FIELD_LABELS.get(key, key), baseline.get(key, ""), _status_value_label(key, value))
            for key, value in changes.items()
        ]
    return []


def _current(proposal: AdvisoryProposal, advisory: SecurityAdvisory, team: Any) -> dict[str, Any] | None:
    """What the values the proposal changes hold now, keyed like its baseline.

    None when nothing it changes can have moved: a new update, or a product
    added. A pending proposal is diffed against this rather than the baseline,
    so "Now" is what approving actually replaces.
    """
    baseline = proposal.baseline or {}
    payload = proposal.payload or {}
    if proposal.kind == Kind.POST_UPDATE:
        if payload.get("kind") == "update":
            return None
        return {"remediation_status": advisory.remediation_status}
    if proposal.kind == Kind.EDIT_UPDATE:
        _event, note = advisory_service.current_message(advisory, payload.get("event_id", ""))
        return {**baseline, "note": note}
    if proposal.kind == Kind.EDIT_ADVISORY:
        values = _advisory_values(advisory.id, team)
        return {key: values.get(key, "") for key in baseline}
    if proposal.kind == Kind.PRODUCT_STATUS:
        try:
            rows, _subject = _status_link(advisory, payload)
        except _Invalid:
            return {}
        values = _status_values(rows[0])
        return {**baseline, **{key: values.get(key, "") for key in payload.get("changes") or {}}}
    return None


def _is_stale(proposal: AdvisoryProposal, current: dict[str, Any] | None) -> bool:
    """Whether something the proposal changes has moved since it was sent.

    Approval still applies what was proposed; this is so the reviewer knows
    they are not only reading the agent's change but overwriting a newer one.
    """
    if current is None:
        return False
    baseline = proposal.baseline or {}
    return any(baseline.get(key) != value for key, value in current.items()) or not current


def proposal_row(
    proposal: AdvisoryProposal, advisory: SecurityAdvisory | None = None, team: Any = None
) -> dict[str, Any]:
    """Everything the review shows for one proposal."""
    payload = proposal.payload or {}
    baseline = proposal.baseline or {}
    meta = KIND_META.get(proposal.kind, {"label": proposal.get_kind_display(), "icon": "fas fa-pen"})
    pending = proposal.status == AdvisoryProposal.Status.PENDING
    current = _current(proposal, advisory, team) if pending and advisory is not None else None

    update_kind = payload.get("kind", "") if proposal.kind == Kind.POST_UPDATE else ""
    moves_to = REMEDIATION_META.get(update_kind) if update_kind and update_kind != "update" else None
    subject = baseline.get("subject") or baseline.get("product") or ""
    if proposal.kind == Kind.POST_UPDATE:
        headline = f"Move the status to {moves_to['label']}" if moves_to else "Post an update"
    elif proposal.kind == Kind.EDIT_UPDATE:
        headline = "Reword an update"
    elif proposal.kind == Kind.EDIT_ADVISORY:
        labels = [
            ADVISORY_FIELDS[key]
            for key in ADVISORY_FIELDS
            if key in {_field_key(f) for f in payload.get("fields") or {}}
        ]
        headline = "Change the " + _listed([label if label == "CVSS" else label.lower() for label in labels])
    elif proposal.kind == Kind.PRODUCT_STATUS:
        headline = f"Change the status of {subject}"
    else:
        headline = f"Add {subject}" if not baseline.get("listed") else f"Add releases to {subject}"

    releases = []
    if proposal.kind == Kind.ADD_PRODUCT and (release_ids := payload.get("release_ids")):
        releases = list(Release.objects.filter(id__in=release_ids).values_list("name", flat=True))

    return {
        "id": proposal.id,
        "kind": proposal.kind,
        "kind_label": meta["label"],
        "icon": meta["icon"],
        "headline": headline,
        "status": proposal.status,
        "status_label": proposal.get_status_display(),
        "status_variant": OUTCOME_VARIANTS.get(proposal.status, "secondary"),
        "is_pending": pending,
        "from_agent": proposal.channel == "agent",
        "submitted_by": _person(proposal.submitted_by),
        "submitted_via": proposal.submitted_token_description,
        "submitted_at": proposal.submitted_at,
        "submitted_display": display_date(proposal.submitted_at),
        "context": proposal.context,
        # A new update: its text, and the state it moves the advisory to.
        "note": payload.get("note", ""),
        "proposed_note": payload.get("proposed_note", ""),
        "moves_to": moves_to,
        "update_kind": update_kind,
        # An edit to an update: which one, so the timeline can show it in place.
        "event_id": payload.get("event_id", ""),
        "changes": _changes(proposal, current if current is not None else baseline),
        "releases": releases,
        "is_text": proposal.kind in (Kind.POST_UPDATE, Kind.EDIT_UPDATE),
        "is_stale": _is_stale(proposal, current),
        "decided_by": _person(proposal.decided_by) if proposal.decided_at and proposal.decided_by_id else "",
        "decided_at": proposal.decided_at,
        "decided_display": display_date(proposal.decided_at) if proposal.decided_at else "",
        "decision_note": proposal.decision_note,
        "revised": proposal.revised,
    }


def advisory_proposals(team: Any, advisory_id: str) -> ServiceResult[dict[str, Any]]:
    """The review for one advisory: what is waiting, and what was decided lately."""
    advisory = find_advisory(team, advisory_id)
    if advisory is None:
        return ServiceResult.failure("Advisory not found", status_code=404)
    rows = advisory.proposals.select_related("submitted_by", "decided_by")
    pending = [
        proposal_row(p, advisory, team)
        for p in rows.filter(status=AdvisoryProposal.Status.PENDING).order_by("submitted_at")
    ]
    decided_qs = rows.exclude(status=AdvisoryProposal.Status.PENDING).order_by("-decided_at", "-submitted_at")
    decided_total = decided_qs.count()
    decided = [proposal_row(p) for p in decided_qs[:RECENT_DECIDED]]
    return ServiceResult.success(
        {
            "pending": pending,
            "pending_count": len(pending),
            "pending_updates": [p for p in pending if p["kind"] == Kind.POST_UPDATE],
            "pending_edits": {p["event_id"]: p for p in pending if p["kind"] == Kind.EDIT_UPDATE},
            "pending_record": [p for p in pending if p["kind"] not in (Kind.POST_UPDATE, Kind.EDIT_UPDATE)],
            "decided": decided,
            "decided_total": decided_total,
            "stale_count": sum(1 for p in pending if p["is_stale"]),
        }
    )


def get_proposal(team: Any, advisory_id: str, proposal_id: str) -> ServiceResult[dict[str, Any]]:
    advisory = find_advisory(team, advisory_id)
    proposal = (
        advisory.proposals.select_related("submitted_by", "decided_by").filter(pk=proposal_id).first()
        if advisory is not None
        else None
    )
    if proposal is None:
        return ServiceResult.failure("Proposed change not found", status_code=404)
    return ServiceResult.success(proposal_row(proposal, advisory, team))


def pending_counts(team: Any) -> dict[str, int]:
    """How many changes wait for review on each of the workspace's advisories."""
    rows = (
        AdvisoryProposal.objects.filter(team=team, status=AdvisoryProposal.Status.PENDING)
        .values("advisory_id")
        .annotate(n=Count("id"))
    )
    return {row["advisory_id"]: row["n"] for row in rows}

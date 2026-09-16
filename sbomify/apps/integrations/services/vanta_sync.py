"""Read a workspace's Vanta programme and write it into the controls models.

The whole point of this module is that it produces nothing new. A Vanta
framework becomes a ``ControlCatalog``, its controls become ``Control`` rows,
and each control's state becomes a ``ControlStatus`` at workspace scope. From
there the trust center, the product pages and the scoring in
``status_service`` all work exactly as they do for a catalogue somebody
activated by hand.

Two shapes of the Vanta API drive the code:

* A control's **status is not on the list endpoint.** ``/v1/frameworks/{id}/
  controls`` returns the control's identity and text; only ``/v1/controls/
  {id}`` carries ``status``. So a sync costs one request per control, which is
  why it lives in a task and why details are cached across frameworks: the
  same control is usually mapped into several of them.

* **Frameworks are identified by id, not by name.** A renamed framework has to
  update in place or a workspace ends up publishing the same programme twice.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from sbomify.apps.controls.models import Control, ControlCatalog, ControlStatus, ControlStatusLog
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.integrations.providers.vanta import VANTA, VantaClient
from sbomify.apps.integrations.services.connections import access_token
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.integrations.models import Integration

logger = getLogger(__name__)

# Vanta's own words for how far a control has got, mapped onto the four states
# sbomify scores. ``NO_EVIDENCE_MAPPED`` and ``NOT_STARTED`` are different
# problems in Vanta but the same claim here: the control is not met.
#
# Nothing maps to ``not_applicable``. Vanta expresses "does not apply" by
# leaving the control out of the framework, so a control that reaches this
# function applies by definition, and inventing an N/A would quietly remove it
# from the denominator of a published score.
VANTA_STATUS_MAP: dict[str, str] = {
    "COMPLETED": ControlStatus.Status.COMPLIANT,
    "IN_PROGRESS": ControlStatus.Status.PARTIAL,
    "NOT_STARTED": ControlStatus.Status.NOT_IMPLEMENTED,
    "NO_EVIDENCE_MAPPED": ControlStatus.Status.NOT_IMPLEMENTED,
}

# What the notes field on a synced status says. It is visible on the trust
# center, so it reads as copy rather than as a debug string.
SYNC_NOTE = "Synced from Vanta"

_UNGROUPED = "General"


@dataclass
class SyncSummary:
    """What one run did, for the settings page and the task log."""

    frameworks: int = 0
    controls: int = 0
    statuses_changed: int = 0
    controls_removed: int = 0
    framework_names: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def sync(integration: Integration) -> ServiceResult[dict[str, Any]]:
    """Pull every framework the connected Vanta account tracks.

    Raises ``ProviderAuthError`` when the credential is gone, because that is
    not a result the caller should record as a failed sync and retry; the
    generic runner turns it into a reconnect prompt.
    """
    token = access_token(integration, VANTA)
    client = VantaClient(token, settings.VANTA_API_BASE_URL)

    summary = SyncSummary()
    # A control mapped into three frameworks is one control in Vanta, so its
    # detail is fetched once. On a SOC 2 plus ISO 27001 account this is the
    # difference between roughly 400 requests and roughly 250.
    detail_cache: dict[str, dict[str, Any]] = {}

    seen_catalog_ids: list[str] = []
    for framework in client.frameworks():
        framework_id = _text(framework.get("id"))
        if not framework_id:
            continue

        catalog = _upsert_catalog(integration, framework, framework_id)
        seen_catalog_ids.append(catalog.id)
        summary.frameworks += 1
        summary.framework_names.append(catalog.name)

        controls = list(client.framework_controls(framework_id))
        _sync_framework_controls(client, catalog, controls, detail_cache, summary)

    if seen_catalog_ids:
        _retire_missing_catalogs(integration, seen_catalog_ids)
    else:
        # Nothing was returned. A real account always tracks at least one
        # framework, so this is far more likely to be a response shape the
        # parser did not recognise than a workspace that genuinely tracks
        # nothing, and retiring on it would silently empty the trust center
        # and need every framework switched back on by hand. Left alone and
        # logged; the next sync that returns frameworks retires properly.
        logger.warning(
            "Vanta returned no frameworks for workspace %s, leaving published ones alone", integration.team.key
        )

    logger.info(
        "Vanta sync for workspace %s: %d frameworks, %d controls, %d status changes",
        integration.team.key,
        summary.frameworks,
        summary.controls,
        summary.statuses_changed,
    )
    return ServiceResult.success(summary.as_dict())


def _sync_framework_controls(
    client: VantaClient,
    catalog: ControlCatalog,
    controls: list[dict[str, Any]],
    detail_cache: dict[str, dict[str, Any]],
    summary: SyncSummary,
) -> None:
    """Write one framework's controls and statuses, and drop what Vanta dropped."""
    seen_control_ids: list[str] = []

    for sort_order, payload in enumerate(controls):
        external_id = _text(payload.get("id"))
        if not external_id:
            continue

        detail = detail_cache.get(external_id)
        if detail is None:
            detail = client.control(external_id)
            detail_cache[external_id] = detail

        control = _upsert_control(catalog, payload, external_id, sort_order)
        seen_control_ids.append(control.id)
        summary.controls += 1

        if _upsert_status(control, detail):
            summary.statuses_changed += 1

    # A control Vanta no longer maps into this framework is deleted rather
    # than left behind: a stale row has no status, so it would count as "not
    # met" and drag down a score published on a public page.
    #
    # Only when this framework actually returned controls. The client is
    # deliberately tolerant of a response it cannot parse, which means "no
    # controls" and "a shape we did not recognise" arrive here as the same
    # empty list, and pruning against it would delete the whole framework and
    # record the run as a success.
    if not seen_control_ids:
        return

    # The per-model figure, not the total: ``delete()`` returns every row it
    # touched, and each control takes its status and its status log with it, so
    # the total would report a handful of controls as dozens.
    _total, by_model = Control.objects.filter(catalog=catalog).exclude(id__in=seen_control_ids).delete()
    summary.controls_removed += by_model.get("controls.Control", 0)


def _upsert_catalog(integration: Integration, framework: dict[str, Any], framework_id: str) -> ControlCatalog:
    """The catalogue for one Vanta framework, matched on its Vanta id.

    New catalogues arrive active but **unpublished**: the workspace is
    tracking the framework, which is what ``is_active`` says, and nobody has
    yet decided to put it on a page their customers read, which is what
    ``is_published`` says. Connecting an account reads data; publishing is a
    second, deliberate act, the same way ``product:set_visibility`` sits above
    the tier that creates products. The Integrations tab is where someone
    makes that choice.
    """
    name = _fit(
        ControlCatalog,
        "name",
        _text(framework.get("displayName")) or _text(framework.get("shorthandName")) or framework_id,
    )
    version = _fit(ControlCatalog, "version", _text(framework.get("shorthandName")))
    if version == name:
        version = ""

    catalog = ControlCatalog.objects.filter(
        team=integration.team, source=ControlCatalog.Source.VANTA, external_id=framework_id
    ).first()

    if catalog is not None:
        if catalog.name != name or catalog.version != version:
            catalog.name = name
            catalog.version = version
            try:
                with transaction.atomic():
                    catalog.save(update_fields=["name", "version", "updated_at"])
            except IntegrityError:
                # The workspace already holds a catalogue under that exact
                # name and version, almost always the built-in copy of the
                # same framework. Keep the rename but make it distinguishable
                # rather than failing the whole sync over a label.
                catalog.version = _fit(ControlCatalog, "version", framework_id)
                catalog.save(update_fields=["name", "version", "updated_at"])
        return catalog

    try:
        with transaction.atomic():
            return ControlCatalog.objects.create(
                team=integration.team,
                name=name,
                version=version,
                source=ControlCatalog.Source.VANTA,
                external_id=framework_id,
                is_published=False,
            )
    except IntegrityError:
        # Two different collisions land here. Another sync of the same account
        # got the framework in first, in which case its row is the one to go on
        # with: creating a second would split this framework's controls and
        # statuses across two catalogs that later syncs pick between at random.
        raced = ControlCatalog.objects.filter(
            team=integration.team, source=ControlCatalog.Source.VANTA, external_id=framework_id
        ).first()
        if raced is not None:
            return raced

        # Otherwise the workspace already holds a catalog under this exact name
        # and version, almost always its own copy of the same framework, and the
        # synced one needs a label of its own.
        return ControlCatalog.objects.create(
            team=integration.team,
            name=name,
            version=_fit(ControlCatalog, "version", framework_id),
            source=ControlCatalog.Source.VANTA,
            external_id=framework_id,
            is_published=False,
        )


def _upsert_control(catalog: ControlCatalog, payload: dict[str, Any], external_id: str, sort_order: int) -> Control:
    """One control row, keyed by the code a reader recognises.

    ``Control`` is unique on (catalog, control_id), and ``control_id`` is the
    framework's own code ("CC1.1"). Vanta returns that as ``externalId``; when
    a custom control has none, its Vanta id stands in so the row still has a
    stable key.
    """
    # Truncating a code could in principle collide two controls onto one row,
    # since (catalog, control_id) is the key. A framework code is a handful of
    # characters, so this only bites on a custom control with a 50+ character
    # slug, and merging two of those beats failing the whole sync.
    control_id = _fit(Control, "control_id", _text(payload.get("externalId")) or external_id)
    domains = payload.get("domains")
    group = _text(domains[0]) if isinstance(domains, list) and domains else _UNGROUPED

    control, _created = Control.objects.update_or_create(
        catalog=catalog,
        control_id=control_id,
        defaults={
            "group": _fit(Control, "group", group or _UNGROUPED),
            "title": _fit(Control, "title", _text(payload.get("name")) or control_id),
            "description": _text(payload.get("description")),
            "external_id": _fit(Control, "external_id", external_id),
            "sort_order": sort_order,
        },
    )
    return control


def _upsert_status(control: Control, detail: dict[str, Any]) -> bool:
    """Write the workspace-scope status for a control. True if it moved.

    Product-scope statuses are left alone. Vanta describes the organisation,
    not one product, so an override someone set on a product stays theirs.
    """
    status = VANTA_STATUS_MAP.get(_text(detail.get("status")).upper(), ControlStatus.Status.NOT_IMPLEMENTED)

    existing = ControlStatus.objects.filter(control=control, product__isnull=True).first()
    old_status = existing.status if existing else ""

    ControlStatus.objects.update_or_create(
        control=control,
        product=None,
        defaults={"status": status, "notes": SYNC_NOTE, "updated_by": None},
    )

    if old_status == status:
        return False

    ControlStatusLog.objects.create(
        control=control,
        product=None,
        old_status=old_status,
        new_status=status,
        changed_by=None,
    )
    return True


def _retire_missing_catalogs(integration: Integration, seen_catalog_ids: list[str]) -> None:
    """Unpublish frameworks the account no longer tracks.

    Not deleted: the workspace may have turned the framework off in Vanta for
    a quarter and turned it back on, and deleting takes the status history with
    it. Unpublishing is enough to stop a claim nobody is backing any more.
    """
    ControlCatalog.objects.filter(team=integration.team, source=ControlCatalog.Source.VANTA, is_published=True).exclude(
        id__in=seen_catalog_ids
    ).update(is_published=False, updated_at=timezone.now())


def _text(value: Any) -> str:
    """A trimmed string for anything the API might have left null."""
    return value.strip() if isinstance(value, str) else ""


def _fit(model: type[models.Model], field_name: str, value: str) -> str:
    """``value`` cut to what its column will actually take.

    Every string here is someone else's, and the columns it lands in are
    bounded: ``control_id`` is 50 characters, ``group`` 255, ``title`` 500. One
    over-long control slug in a Vanta account would otherwise raise a
    ``DataError`` that fails that sync and every sync after it, with nothing on
    the settings page to say which control is at fault.

    The limit is read off the field rather than written out, so widening a
    column does not leave a stale number here.
    """
    # getattr rather than attribute access: get_field is typed as returning
    # any field kind, and only the concrete char fields carry a max_length.
    max_length = getattr(model._meta.get_field(field_name), "max_length", None)
    return value[:max_length] if isinstance(max_length, int) else value

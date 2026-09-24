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

    # The credential this run belongs to. A sync is one request per control, so
    # it stays open for minutes, and a reconnect or a disconnect inside that
    # window makes everything below it a write on behalf of an account that is
    # no longer the connected one. Checked between frameworks rather than
    # between controls: the run already spends a network round trip per control,
    # but bounding the damage to one framework is what matters and a query per
    # control would buy very little for it.
    generation = integration.connected_at

    summary = SyncSummary()
    # A control mapped into three frameworks is one control in Vanta, so its
    # detail is fetched once. On a SOC 2 plus ISO 27001 account this is the
    # difference between roughly 400 requests and roughly 250.
    detail_cache: dict[str, dict[str, Any]] = {}

    seen_catalog_ids: list[str] = []
    for framework in client.frameworks():
        if _superseded(integration, generation):
            return _superseded_result(integration)

        framework_id = _text(framework.get("id"))
        if not framework_id:
            continue

        catalog = _upsert_catalog(integration, framework, framework_id)
        seen_catalog_ids.append(catalog.id)
        summary.frameworks += 1
        summary.framework_names.append(catalog.name)

        controls = list(client.framework_controls(framework_id))
        _sync_framework_controls(client, catalog, controls, detail_cache, summary, integration, generation)

    if _superseded(integration, generation):
        return _superseded_result(integration)

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


def _superseded(integration: Integration, generation: Any) -> bool:
    """Whether the connection this run started on is still the connected one.

    ``connected_at`` moves when somebody reconnects, and the row is gone after a
    disconnect, so one cheap read answers both.
    """
    from sbomify.apps.integrations.models import Integration as IntegrationModel

    return not IntegrationModel.objects.filter(pk=integration.pk, connected_at=generation).exists()


def _superseded_result(integration: Integration) -> ServiceResult[dict[str, Any]]:
    logger.info(
        "Vanta sync for workspace %s stopped: the connection was replaced while it was running",
        integration.team.key,
    )
    return ServiceResult.failure("The connection was replaced while this sync was running.", status_code=409)


def _sync_framework_controls(
    client: VantaClient,
    catalog: ControlCatalog,
    controls: list[dict[str, Any]],
    detail_cache: dict[str, dict[str, Any]],
    summary: SyncSummary,
    integration: Integration,
    generation: Any,
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

    # Deleting is the destructive half, and the loop above has just spent a
    # request per control getting here, so the connection is re-checked before
    # it runs rather than trusted from whenever this framework started.
    if _superseded(integration, generation):
        return

    missing = Control.objects.filter(catalog=catalog).exclude(id__in=seen_control_ids)

    # A product override is a decision somebody made about their own product,
    # and deleting the control cascades it away along with its history. This
    # sync does not touch product scope anywhere else and must not do it here
    # by the back door, so a control carrying one is kept.
    #
    # Its workspace-scope status goes, because that is the part Vanta was
    # answering for and it is now stale: left behind it would keep scoring a
    # control the framework no longer lists. What remains is the override and
    # the history behind it, which is what somebody would come looking for.
    overridden = list(missing.filter(statuses__product__isnull=False).distinct().values_list("id", flat=True))
    if overridden:
        ControlStatus.objects.filter(control_id__in=overridden, product__isnull=True).delete()
        logger.info(
            "Vanta dropped %d control(s) in %s that carry product overrides; kept them and their overrides",
            len(overridden),
            catalog.name,
        )

    # The per-model figure, not the total: ``delete()`` returns every row it
    # touched, and each control takes its status and its status log with it, so
    # the total would report a handful of controls as dozens.
    _total, by_model = missing.exclude(id__in=overridden).delete()
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
    """One control row, found by Vanta's id and labelled with the reader's code.

    ``Control`` is unique on (catalog, control_id), and ``control_id`` is the
    framework's own code ("CC1.1"), which is what somebody reading the trust
    center recognises. It is not identity: Vanta can rename a code, and keying
    on it would make the renamed control a new row, which the prune below then
    deletes, taking the control's statuses and its whole status history with
    it. ``external_id`` is Vanta's own id and does not move, so the row is
    found by that and the code is just another field to update.
    """
    # Truncating a code could in principle collide two controls onto one row,
    # since (catalog, control_id) is the key. A framework code is a handful of
    # characters, so this only bites on a custom control with a 50+ character
    # slug, and merging two of those beats failing the whole sync.
    control_id = _fit(Control, "control_id", _text(payload.get("externalId")) or external_id)
    domains = payload.get("domains")
    group = _text(domains[0]) if isinstance(domains, list) and domains else _UNGROUPED
    fitted_external_id = _fit(Control, "external_id", external_id)

    fields = {
        "group": _fit(Control, "group", group or _UNGROUPED),
        "title": _fit(Control, "title", _text(payload.get("name")) or control_id),
        "description": _text(payload.get("description")),
        "sort_order": sort_order,
    }

    existing = Control.objects.filter(catalog=catalog, external_id=fitted_external_id).first()
    if existing is not None:
        # A rename can land on a code some other row in this catalogue already
        # holds, and (catalog, control_id) is unique. Keeping our own code is
        # the safe answer: the identity is right either way, and one stale
        # label beats failing the sync.
        if existing.control_id != control_id and not (
            Control.objects.filter(catalog=catalog, control_id=control_id).exclude(pk=existing.pk).exists()
        ):
            fields["control_id"] = control_id
        for name, value in fields.items():
            setattr(existing, name, value)
        existing.save(update_fields=[*fields, "updated_at"])
        return existing

    # No row carries this upstream id. A row already holding the code is a
    # different control of Vanta's, so matching on the code would hand it this
    # one's identity: its statuses and its whole history would be reassigned and
    # the old control lost. Vanta deleting and recreating a control under the
    # same code does exactly that.
    #
    # The colliding row is stale by definition, since Vanta no longer lists it,
    # and the prune at the end of this framework takes it. So the new control
    # takes a label of its own for now and the next sync renames it through the
    # branch above, once the code is free.
    if Control.objects.filter(catalog=catalog, control_id=control_id).exists():
        control_id = _fit(Control, "control_id", fitted_external_id)

    control, _created = Control.objects.update_or_create(
        catalog=catalog,
        control_id=control_id,
        defaults={**fields, "external_id": fitted_external_id},
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

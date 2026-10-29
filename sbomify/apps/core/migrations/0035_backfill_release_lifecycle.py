"""Turn existing supersededBy events into supersession edges, and derive each release's support dates.

Each surviving supersededBy event becomes a live edge with drop_in=False, so a
supersession declared before drop-in existed retires nothing on deploy. The
successor links to the release of the same product it names, matched on
version and then name. A successor outside sbomify, or one the live service
refuses (latest, or the release itself), keeps its label only. An edge from
latest is skipped, as the service refuses it, and naming one successor twice
adds no second live edge. Release-level endOfSupport and endOfLife events do
start to count, and a release without its own takes the product's date when
that date covers every version.

A frozen copy of the dates half of recompute_release_lifecycle; superseded_at
needs no backfill, since only a drop-in edge sets it.

Running it again adds nothing, and the reverse removes what it wrote, so the
migration can be unapplied and applied again. The reverse is for development:
it removes every edge with a CLE event, no actor and drop_in=False, which is
what the backfill writes, so an edge with the same shape that a caller without
a user declared after the migration ran goes with it. Reversing to core 0033
drops the table in any case.
"""

from collections import defaultdict

from django.db import migrations


def _surviving(events):
    voided = {
        event.withdrawn_event_id
        for event in events
        if event.event_type == "withdrawn" and event.withdrawn_event_id is not None
    }
    return [event for event in events if event.event_id not in voided]


def _fold_dates(events):
    support_ends = {}
    end_of_life = None
    for event in events:
        if event.event_type == "endOfSupport":
            support_ends[event.support_id] = event.effective.date()
        elif event.event_type == "endOfLife":
            end_of_life = event.effective.date()
    return max(support_ends.values(), default=None), end_of_life


def _covers_every_version(versions):
    if not versions:
        return True
    return any(str(entry.get("range", "")).strip().endswith("/*") for entry in versions if isinstance(entry, dict))


def backfill_release_lifecycle(apps, schema_editor):
    Release = apps.get_model("core", "Release")
    ReleaseSupersession = apps.get_model("core", "ReleaseSupersession")
    ReleaseCLEEvent = apps.get_model("sboms", "ReleaseCLEEvent")
    ProductCLEEvent = apps.get_model("sboms", "ProductCLEEvent")

    product_ids = set(ReleaseCLEEvent.objects.order_by().values_list("release__product_id", flat=True).distinct())
    product_ids |= set(ProductCLEEvent.objects.order_by().values_list("product_id", flat=True).distinct())
    linked_events = set(ReleaseSupersession.objects.exclude(cle_event=None).values_list("cle_event_id", flat=True))
    for product_id in product_ids:
        releases = {release.pk: release for release in Release.objects.filter(product_id=product_id)}
        by_version = {release.version: release for release in releases.values() if release.version}
        by_name = {release.name: release for release in releases.values()}
        named = set(
            ReleaseSupersession.objects.filter(from_release__product_id=product_id, withdrawn_at=None).values_list(
                "from_release_id", "successor_label"
            )
        )

        by_release = defaultdict(list)
        for event in ReleaseCLEEvent.objects.filter(release__product_id=product_id).order_by("release_id", "event_id"):
            by_release[event.release_id].append(event)

        edges = []
        for release_id, events in by_release.items():
            predecessor = releases[release_id]
            for event in _surviving(events):
                label = event.superseded_by_version
                if event.event_type != "supersededBy" or not label or predecessor.is_latest:
                    continue
                if event.pk in linked_events or (predecessor.pk, label) in named:
                    continue
                named.add((predecessor.pk, label))
                successor = by_version.get(label) or by_name.get(label)
                if successor is not None and (successor.pk == predecessor.pk or successor.is_latest):
                    successor = None
                edges.append(
                    ReleaseSupersession(
                        from_release_id=predecessor.pk,
                        to_release_id=successor.pk if successor else None,
                        successor_label=label,
                        effective=event.effective,
                        reason=event.reason,
                        cle_event_id=event.pk,
                    )
                )

        product_events = _surviving(list(ProductCLEEvent.objects.filter(product_id=product_id).order_by("event_id")))
        product_support, product_life = _fold_dates(
            event for event in product_events if _covers_every_version(event.versions)
        )

        fields = ["end_of_support", "end_of_life", "effective_end_of_support", "effective_end_of_life"]
        changed = []
        for pk, release in releases.items():
            end_of_support, end_of_life = _fold_dates(_surviving(by_release[pk]))
            derived = (end_of_support, end_of_life, end_of_support or product_support, end_of_life or product_life)
            if tuple(getattr(release, field) for field in fields) != derived:
                for field, value in zip(fields, derived):
                    setattr(release, field, value)
                changed.append(release)

        ReleaseSupersession.objects.bulk_create(edges)
        Release.objects.bulk_update(changed, fields)


def reverse_backfill_release_lifecycle(apps, schema_editor):
    """Remove what the backfill writes: the edges it made from events, and the derived dates."""
    Release = apps.get_model("core", "Release")
    ReleaseSupersession = apps.get_model("core", "ReleaseSupersession")

    ReleaseSupersession.objects.filter(drop_in=False, actor=None).exclude(cle_event=None).delete()
    Release.objects.exclude(
        end_of_support=None, end_of_life=None, effective_end_of_support=None, effective_end_of_life=None
    ).update(end_of_support=None, end_of_life=None, effective_end_of_support=None, effective_end_of_life=None)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0034_release_lifecycle"),
    ]

    operations = [
        migrations.RunPython(backfill_release_lifecycle, reverse_backfill_release_lifecycle),
    ]

"""Turn existing supersededBy events into supersession edges, and derive each release's support dates.

Each surviving supersededBy event becomes a live edge with drop_in=False, so a
supersession declared before drop-in existed retires nothing on deploy. The
successor links to the release of the same product it names, matched on
version and then name. A successor outside sbomify, or one the live service
refuses (latest, or the release itself), keeps its label only. An edge from
latest is skipped, as the service refuses it, and naming one successor twice
adds no second live edge. Release-level endOfSupport and endOfLife events do
start to count.

A frozen copy of the dates half of recompute_release_lifecycle; superseded_at
needs no backfill, since only a drop-in edge sets it.
"""

from collections import defaultdict

from django.db import migrations


def backfill_release_lifecycle(apps, schema_editor):
    Release = apps.get_model("core", "Release")
    ReleaseSupersession = apps.get_model("core", "ReleaseSupersession")
    ReleaseCLEEvent = apps.get_model("sboms", "ReleaseCLEEvent")

    product_ids = ReleaseCLEEvent.objects.order_by().values_list("release__product_id", flat=True).distinct()
    for product_id in product_ids:
        releases = {release.pk: release for release in Release.objects.filter(product_id=product_id)}
        by_version = {release.version: release for release in releases.values() if release.version}
        by_name = {release.name: release for release in releases.values()}
        events = list(ReleaseCLEEvent.objects.filter(release__product_id=product_id).order_by("release_id", "event_id"))
        voided = {
            (event.release_id, event.withdrawn_event_id)
            for event in events
            if event.event_type == "withdrawn" and event.withdrawn_event_id is not None
        }

        edges = []
        named = set()
        support_ends = defaultdict(dict)
        life_ends = {}
        for event in events:
            if (event.release_id, event.event_id) in voided:
                continue
            predecessor = releases[event.release_id]
            label = event.superseded_by_version
            if event.event_type == "supersededBy" and label and not predecessor.is_latest:
                if (predecessor.pk, label) in named:
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
            elif event.event_type == "endOfSupport":
                support_ends[event.release_id][event.support_id] = event.effective.date()
            elif event.event_type == "endOfLife":
                life_ends[event.release_id] = event.effective.date()

        changed = []
        for pk, release in releases.items():
            derived = (max(support_ends[pk].values(), default=None), life_ends.get(pk))
            if (release.end_of_support, release.end_of_life) != derived:
                release.end_of_support, release.end_of_life = derived
                changed.append(release)

        ReleaseSupersession.objects.bulk_create(edges)
        Release.objects.bulk_update(changed, ["end_of_support", "end_of_life"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0034_release_lifecycle"),
    ]

    operations = [
        migrations.RunPython(backfill_release_lifecycle, migrations.RunPython.noop),
    ]

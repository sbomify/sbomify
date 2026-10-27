"""Resolve existing supersededBy events to releases, and derive each release's support dates.

Every existing edge keeps drop_in=False, so a supersession declared before
drop-in existed retires nothing on deploy. Release-level endOfSupport and
endOfLife events do start to count.

A frozen copy of the dates half of recompute_release_lifecycle; superseded_at
needs no backfill, since only a drop-in edge sets it.
"""

from collections import defaultdict

from django.db import migrations


def backfill_release_lifecycle(apps, schema_editor):
    Release = apps.get_model("core", "Release")
    ReleaseCLEEvent = apps.get_model("sboms", "ReleaseCLEEvent")

    product_ids = set(ReleaseCLEEvent.objects.order_by().values_list("release__product_id", flat=True))
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

        resolved = []
        support_ends = defaultdict(dict)
        life_ends = {}
        for event in events:
            if event.event_type == "supersededBy" and event.superseded_by_release_id is None:
                version = event.superseded_by_version
                successor = by_version.get(version) or by_name.get(version)
                if successor is not None and successor.pk != event.release_id and not successor.is_latest:
                    event.superseded_by_release_id = successor.pk
                    resolved.append(event)
            if (event.release_id, event.event_id) in voided:
                continue
            if event.event_type == "endOfSupport":
                support_ends[event.release_id][event.support_id] = event.effective.date()
            elif event.event_type == "endOfLife":
                life_ends[event.release_id] = event.effective.date()

        changed = []
        for pk, release in releases.items():
            derived = (max(support_ends[pk].values(), default=None), life_ends.get(pk))
            if (release.end_of_support, release.end_of_life) != derived:
                release.end_of_support, release.end_of_life = derived
                changed.append(release)

        ReleaseCLEEvent.objects.bulk_update(resolved, ["superseded_by_release"])
        Release.objects.bulk_update(changed, ["end_of_support", "end_of_life"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0034_release_lifecycle"),
        ("sboms", "0069_release_cle_event_supersession"),
    ]

    operations = [
        migrations.RunPython(backfill_release_lifecycle, migrations.RunPython.noop),
    ]

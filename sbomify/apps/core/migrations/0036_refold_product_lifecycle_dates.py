"""Refold every product's end_of_support and end_of_life the way its releases inherit them.

Before this, the columns held the last surviving event of each type, whatever
its support policy or version range. Releases now inherit only events for
every version, the latest per support policy and then the latest across
policies, and new product writes fold the columns the same way. Products that
already had events kept the old fold until their next write, so the API showed
one date while their releases followed another.

A frozen copy of release_lifecycle.product_dates. Running it again changes
nothing; the reverse leaves the columns as they are, since the next product
write refolds them anyway.
"""

from django.db import migrations


def _surviving(events):
    voided = {
        event.withdrawn_event_id
        for event in events
        if event.event_type == "withdrawn" and event.withdrawn_event_id is not None
    }
    return [event for event in events if event.event_id not in voided]


def _covers_every_version(versions):
    if not versions:
        return True
    return any(str(entry.get("range", "")).strip().endswith("/*") for entry in versions if isinstance(entry, dict))


def _product_dates(events):
    support_ends = {}
    end_of_life = None
    for event in _surviving(events):
        if not _covers_every_version(event.versions):
            continue
        if event.event_type == "endOfSupport":
            support_ends[event.support_id] = event.effective.date()
        elif event.event_type == "endOfLife":
            end_of_life = event.effective.date()
    return max(support_ends.values(), default=None), end_of_life


def refold_product_lifecycle_dates(apps, schema_editor):
    Product = apps.get_model("sboms", "Product")
    ProductCLEEvent = apps.get_model("sboms", "ProductCLEEvent")

    product_ids = ProductCLEEvent.objects.order_by().values_list("product_id", flat=True).distinct()
    for product_id in product_ids:
        events = list(ProductCLEEvent.objects.filter(product_id=product_id).order_by("event_id"))
        end_of_support, end_of_life = _product_dates(events)
        Product.objects.filter(pk=product_id).update(end_of_support=end_of_support, end_of_life=end_of_life)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0035_backfill_release_lifecycle"),
    ]

    operations = [
        migrations.RunPython(refold_product_lifecycle_dates, migrations.RunPython.noop),
    ]

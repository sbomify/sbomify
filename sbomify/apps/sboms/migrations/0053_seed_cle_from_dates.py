"""Seed CLE events from existing product lifecycle date fields."""

import sys
from datetime import datetime, timezone

from django.db import migrations, models, transaction


def seed_cle_events(apps, schema_editor):
    """Create CLE events from existing release_date, end_of_support, end_of_life fields."""
    Product = apps.get_model("sboms", "Product")
    ProductCLEEvent = apps.get_model("sboms", "ProductCLEEvent")

    # Precompute products that already have CLE events (single query)
    existing_event_product_ids = set(ProductCLEEvent.objects.values_list("product_id", flat=True))

    products = Product.objects.filter(
        models.Q(release_date__isnull=False)
        | models.Q(end_of_support__isnull=False)
        | models.Q(end_of_life__isnull=False)
    )

    for product in products.iterator():
        # Skip products that already have CLE events (idempotency)
        if product.pk in existing_event_product_ids:
            continue

        try:
            with transaction.atomic():
                event_id = 0

                if product.release_date:
                    event_id += 1
                    ProductCLEEvent.objects.create(
                        product=product,
                        event_id=event_id,
                        event_type="released",
                        effective=datetime(
                            product.release_date.year,
                            product.release_date.month,
                            product.release_date.day,
                            tzinfo=timezone.utc,
                        ),
                        version="",
                        versions=[],
                        identifiers=[],
                        references=[],
                    )

                if product.end_of_support:
                    event_id += 1
                    ProductCLEEvent.objects.create(
                        product=product,
                        event_id=event_id,
                        event_type="endOfSupport",
                        effective=datetime(
                            product.end_of_support.year,
                            product.end_of_support.month,
                            product.end_of_support.day,
                            tzinfo=timezone.utc,
                        ),
                        versions=[{"range": "vers:generic/*"}],
                        version="",
                        identifiers=[],
                        references=[],
                    )

                if product.end_of_life:
                    event_id += 1
                    ProductCLEEvent.objects.create(
                        product=product,
                        event_id=event_id,
                        event_type="endOfLife",
                        effective=datetime(
                            product.end_of_life.year,
                            product.end_of_life.month,
                            product.end_of_life.day,
                            tzinfo=timezone.utc,
                        ),
                        versions=[{"range": "vers:generic/*"}],
                        version="",
                        identifiers=[],
                        references=[],
                    )
        except Exception as exc:
            sys.stderr.write(f"WARNING: Failed to seed CLE events for product {product.pk}: {exc}\n")
            continue


class Migration(migrations.Migration):
    dependencies = [
        ("sboms", "0052_product_cle"),
    ]

    operations = [
        migrations.RunPython(seed_cle_events, migrations.RunPython.noop),
    ]

"""Refresh the vendored CycloneDX cryptography-registry data file.

The registry versions independently of the CycloneDX spec, so the vendored
copy under ``sboms/data/`` drifts. This fetches the published data file,
sanity-checks its shape, and rewrites the vendored copy. Commit the result.
"""

import json
from typing import Any
from urllib.request import urlopen

from django.core.management.base import BaseCommand, CommandError

from sbomify.apps.sboms import crypto_registry

REGISTRY_URL = "https://cyclonedx.org/schema/cryptography-defs.json"


class Command(BaseCommand):
    help = "Fetch the CycloneDX cryptography registry and rewrite the vendored data file."

    def handle(self, *args: Any, **options: Any) -> None:
        with urlopen(REGISTRY_URL, timeout=30) as response:  # nosec B310 - fixed https URL
            raw = response.read()
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise CommandError(f"Registry response is not JSON: {exc}")
        if not isinstance(data, dict) or "algorithms" not in data or "ellipticCurves" not in data:
            raise CommandError("Registry response missing algorithms/ellipticCurves")
        # Build the lookup tables from the candidate data before writing: a
        # shape drift that would gut normalization is rejected here instead of
        # being committed and discovered in production.
        candidate = crypto_registry.build_tables(data)
        if not candidate.curve_by_name or not candidate.family_by_name:
            raise CommandError("Registry response produced empty lookup tables; refusing to overwrite vendored data")

        previous = crypto_registry.registry_last_updated()
        crypto_registry._DATA_PATH.write_bytes(raw)
        crypto_registry._tables.cache_clear()
        self.stdout.write(
            self.style.SUCCESS(
                f"Registry refreshed: lastUpdated {previous} -> {data.get('lastUpdated')} "
                f"({len(data['algorithms'])} families, "
                f"{sum(len(f.get('curves') or []) for f in data['ellipticCurves'])} curves)"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                "The in-memory tables cleared here belong to this process only; "
                "restart web and worker processes to pick up the new registry."
            )
        )

"""The providers this deployment knows how to connect to.

One tuple, in the order the tiles appear. Everything else about a provider is
on its spec, so nothing here has to grow when a second one arrives.
"""

from __future__ import annotations

from sbomify.apps.integrations.providers.base import ProviderSpec
from sbomify.apps.integrations.providers.vanta import VANTA

PROVIDERS: tuple[ProviderSpec, ...] = (VANTA,)

PROVIDERS_BY_KEY: dict[str, ProviderSpec] = {provider.key: provider for provider in PROVIDERS}


def get_provider(key: str) -> ProviderSpec | None:
    """The spec for ``key``, or None when nothing is registered under it."""
    return PROVIDERS_BY_KEY.get(key)


__all__ = ["PROVIDERS", "PROVIDERS_BY_KEY", "ProviderSpec", "get_provider"]

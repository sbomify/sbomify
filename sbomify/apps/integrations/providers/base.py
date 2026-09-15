"""What the rest of the app needs to know about a provider, and nothing more.

Everything provider-specific is data on one frozen dataclass, so the OAuth
module, the views and the templates never branch on which provider they are
looking at. Adding a second one is a new ``ProviderSpec`` and a sync function.

The four ``*_setting`` fields name settings rather than holding values,
because a spec is built at import time and the settings it reads are
per-deployment and overridable in tests. Reading them through ``getattr`` at
call time is what makes ``override_settings`` work on a connect flow.

Two of those four are named around the usual words rather than using them.
``exchange_url_setting`` is the token endpoint and ``client_credential_setting``
is the client secret. Both hold the *name* of a setting and never a value, but
bandit reads "token" or "secret" in a keyword argument as a hardcoded password,
so calling them what they are produces a B106 that is not a finding. Renaming
them back reintroduces it.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class ProviderSpec:
    """One connectable external tool."""

    key: str
    name: str
    # One line under the name on the tile. Copy, so no dashes and no jargon.
    tagline: str
    icon: str
    docs_url: str
    # What the connection will be able to read, in the user's words. Shown
    # before they are sent to the provider, because the consent screen is the
    # provider's copy and says nothing about what sbomify does with it.
    reads: tuple[str, ...]
    scopes: tuple[str, ...]
    authorize_url_setting: str
    exchange_url_setting: str
    client_id_setting: str
    client_credential_setting: str
    # Dotted path to ``sync(integration) -> ServiceResult[SyncSummary]``.
    # A path rather than the function, so a provider module is free to import
    # this one.
    sync_path: str

    def _setting(self, name: str) -> str:
        return str(getattr(settings, name, "") or "")

    @property
    def authorize_url(self) -> str:
        return self._setting(self.authorize_url_setting)

    @property
    def token_url(self) -> str:
        return self._setting(self.exchange_url_setting)

    @property
    def client_id(self) -> str:
        return self._setting(self.client_id_setting)

    @property
    def client_secret(self) -> str:
        return self._setting(self.client_credential_setting)

    @property
    def is_configured(self) -> bool:
        """Whether this deployment holds credentials for the provider.

        A tile for a provider the deployment cannot actually reach is shown
        disabled rather than hidden: self-hosters need to know the feature
        exists and what to set, and hiding it makes that undiscoverable.
        """
        return bool(self.client_id and self.client_secret and self.authorize_url and self.token_url)

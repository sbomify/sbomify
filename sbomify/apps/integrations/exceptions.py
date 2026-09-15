"""Failures a provider call can produce, split by what the caller should do.

``ProviderAuthError`` is the only one worth a separate type: it is the one
failure a retry cannot fix, because the credential itself is gone. Everything
else is a bad day at the provider and the next scheduled sync will pick it up.
"""

from __future__ import annotations

from sbomify.apps.core.domain.exceptions import ExternalServiceError


class ProviderAuthError(ExternalServiceError):
    """The provider rejected the credential. Someone has to reconnect."""

    error_code = "provider_auth_error"

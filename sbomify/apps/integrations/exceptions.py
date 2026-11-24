"""Failures a provider call can produce, split by what the caller should do.

The split is the whole point of this module, and getting it wrong is
expensive in one direction. ``ProviderAuthError`` means the credential is
gone, which no retry can fix, so the connection is marked as needing a
reconnect and the scheduler stops queueing it. ``ProviderUnavailable`` means
the provider had a bad minute, which the next scheduled sync will fix on its
own.

Treating the second as the first is what turns one 503 into a workspace that
has silently stopped syncing until a human notices and redoes OAuth. So a
non-2xx is only terminal when the provider said so: an authorization failure
is a 4xx, and everything else, including every network error, is transient.
"""

from __future__ import annotations

from sbomify.apps.core.domain.exceptions import ExternalServiceError


class ProviderAuthError(ExternalServiceError):
    """The provider rejected the credential. Someone has to reconnect."""

    error_code = "provider_auth_error"


class ProviderUnavailable(ExternalServiceError):
    """The provider could not answer. The next scheduled sync tries again."""

    error_code = "provider_unavailable"

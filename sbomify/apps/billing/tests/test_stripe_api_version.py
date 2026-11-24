"""The pinned Stripe API version, and what keeps it honest.

Pinning stops a library upgrade moving the version our requests are made
against without a diff to show for it. A pin is only safe while it names a
version Stripe accepts, so the value is checked against the installed
library's own current version rather than trusted as a string.
"""

from __future__ import annotations

import stripe
from django.conf import settings


def _library_current_version() -> str:
    """The version the installed library ships with, before our own pinning.

    Read from the module rather than from ``stripe.api_version``, which the
    billing app config overwrites at startup.
    """
    from stripe._api_version import _ApiVersion

    return _ApiVersion.CURRENT


def test_the_pin_names_a_version_the_library_ships_with():
    """A pin Stripe would reject fails every request, so it cannot be a guess."""
    assert settings.STRIPE_API_VERSION == _library_current_version()


def test_the_library_is_told_the_pinned_version():
    assert stripe.api_version == settings.STRIPE_API_VERSION

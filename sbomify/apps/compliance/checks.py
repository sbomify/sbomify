"""System checks for the compliance app."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Tags, register
from django.core.checks import Warning as CheckWarning

from sbomify.apps.compliance.services.export_signing import key_problem, signing_key


@register(Tags.security)
def check_export_signing_key(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    """A set but unusable CRA_EXPORT_SIGNING_KEY shows at deploy, not only in a log line."""
    problem = key_problem()
    if problem:
        return [
            CheckWarning(
                f"CRA_EXPORT_SIGNING_KEY is set but {problem}.",
                hint="CRA exports stay unsigned until it holds an unencrypted PKCS#8 EC P-256 private key.",
                id="compliance.W001",
            )
        ]
    if signing_key() is not None and not settings.APP_BASE_URL:
        return [
            CheckWarning(
                "CRA_EXPORT_SIGNING_KEY is set but APP_BASE_URL is empty.",
                hint=(
                    "Every signed CRA export names its public key by a URL built from APP_BASE_URL. "
                    "Without it the bundle carries a path a recipient cannot fetch."
                ),
                id="compliance.W002",
            )
        ]
    return []

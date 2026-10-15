"""System checks for the compliance app."""

from __future__ import annotations

from typing import Any

from django.core.checks import CheckMessage, Tags, register
from django.core.checks import Warning as CheckWarning

from sbomify.apps.compliance.services.export_signing import key_problem


@register(Tags.security)
def check_export_signing_key(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    """A set but unusable CRA_EXPORT_SIGNING_KEY shows at deploy, not only in a log line."""
    problem = key_problem()
    if not problem:
        return []
    return [
        CheckWarning(
            f"CRA_EXPORT_SIGNING_KEY is set but {problem}.",
            hint="CRA exports stay unsigned until it holds an unencrypted PKCS#8 EC P-256 private key.",
            id="compliance.W001",
        )
    ]

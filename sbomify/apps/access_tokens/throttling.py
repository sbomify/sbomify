"""Per-token API rate limiting (#1060)."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest
from ninja.throttling import SimpleRateThrottle


class AccessTokenRateThrottle(SimpleRateThrottle):
    """Sliding-window rate limit keyed on the AccessToken pk.

    Two tokens from the same user have independent budgets (the window keys on the
    token row, not the user or the raw token string). Session/anonymous web requests
    carry no resolved token record and are not throttled by this rule.
    """

    def __init__(self, rate: str | None = None) -> None:
        super().__init__(rate or settings.API_TOKEN_RATE_LIMIT)

    def get_cache_key(self, request: HttpRequest) -> str | None:
        record = getattr(request, "access_token_record", None)
        if record is None:
            return None
        return f"throttle_access_token_{record.pk}"

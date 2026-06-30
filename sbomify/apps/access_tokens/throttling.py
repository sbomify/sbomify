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

    # Distinguishes one throttle's sliding window from another's; subclasses override
    # it so they never share (and corrupt) the base throttle's counter.
    cache_key_prefix = "throttle_access_token"

    def __init__(self, rate: str | None = None) -> None:
        super().__init__(rate or settings.API_TOKEN_RATE_LIMIT)

    def get_cache_key(self, request: HttpRequest) -> str | None:
        record = getattr(request, "access_token_record", None)
        if record is None:
            return None
        return f"{self.cache_key_prefix}_{record.pk}"


class AccessTokenHeavyRateThrottle(AccessTokenRateThrottle):
    """Stricter per-token limit for expensive operations (artifact uploads).

    Attached per-operation ALONGSIDE the global AccessTokenRateThrottle (ninja's
    per-operation throttle replaces, not stacks, the global one, so both must be
    passed as a list). The distinct ``cache_key_prefix`` keeps its sliding window
    separate from the global throttle's; a shared key would make both throttles
    read/write the same window and double-count each other.
    """

    cache_key_prefix = "throttle_access_token_heavy"

    def __init__(self, rate: str | None = None) -> None:
        super().__init__(rate or settings.API_TOKEN_HEAVY_RATE_LIMIT)

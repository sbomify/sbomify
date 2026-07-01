"""Per-token API rate limiting (#1060)."""

from __future__ import annotations

from collections.abc import Callable
from math import ceil

from django.conf import settings
from django.http import HttpRequest, HttpResponse
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

    def allow_request(self, request: HttpRequest) -> bool:
        allowed = super().allow_request(request)
        # key is None for session/anonymous requests -> no token budget to report.
        if getattr(self, "key", None) is None:
            return allowed
        # Read the shared throttle instance's per-request state right after super().
        # A concurrent request on the same instance could clobber it between these two
        # lines; the headers are informational, so an occasional stale value is acceptable.
        limit = self.num_requests or 0
        duration = self.duration or 0
        remaining = max(0, limit - len(self.history))
        # ceil so the reset is never reported earlier than a slot actually frees.
        reset = ceil((self.history[-1] if self.history else self.now) + duration)
        budget = (limit, remaining, reset)
        # When several throttles apply (global + heavy), report the one the client hits
        # first: fewest remaining, then soonest reset.
        current = getattr(request, "_access_token_ratelimit", None)
        if current is None or (remaining, reset) < (current[1], current[2]):
            setattr(request, "_access_token_ratelimit", budget)
        return allowed


class RateLimitHeadersMiddleware:
    """Surface the per-token throttle budget as X-RateLimit-* response headers (#1076).

    ``AccessTokenRateThrottle.allow_request`` stashes ``(limit, remaining, reset)`` on the
    request for PAT-authenticated API calls; this middleware copies it onto the response so
    clients can pace themselves instead of only learning the limit from a 429.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        budget = getattr(request, "_access_token_ratelimit", None)
        if budget is not None:
            limit, remaining, reset = budget
            response["X-RateLimit-Limit"] = str(limit)
            response["X-RateLimit-Remaining"] = str(remaining)
            response["X-RateLimit-Reset"] = str(reset)
        return response

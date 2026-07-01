"""Per-token API rate limiting (#1060)."""

from __future__ import annotations

import time
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

    def allow_request(self, request: HttpRequest) -> bool:
        allowed = super().allow_request(request)
        # Ninja reuses one throttle instance across requests, so its per-request scratch
        # (self.key/history/now) is unsafe to read here. Compute the budget from local
        # state and this request's own token instead: get_cache_key() is a pure function
        # of the request, so a fresh cache read for that key can't be corrupted by a
        # concurrent request on the shared instance.
        key = self.get_cache_key(request)
        if key is None:
            return allowed  # session/anonymous -> no token budget to report
        now = time.time()
        duration = self.duration or 0
        limit = self.num_requests or 0
        history = [ts for ts in self.cache.get(key, []) if ts > now - duration]
        remaining = max(0, limit - len(history))
        # ceil so the reset is never reported earlier than a slot actually frees.
        reset = ceil((history[-1] if history else now) + duration)
        budget = (limit, remaining, reset)
        # When several throttles apply (global + heavy), report the one the client hits
        # first: fewest remaining, then soonest reset.
        current = getattr(request, "_access_token_ratelimit", None)
        if current is None or (remaining, reset) < (current[1], current[2]):
            setattr(request, "_access_token_ratelimit", budget)
        return allowed


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

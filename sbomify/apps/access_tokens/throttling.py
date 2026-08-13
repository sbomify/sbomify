"""Per-token API rate limiting (#1060)."""

from __future__ import annotations

import time
from collections.abc import Callable
from math import ceil

from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.base import BaseCache
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

    @property
    def cache(self) -> BaseCache:  # type: ignore[override]
        """The Redis alias that still raises when Redis is unreachable.

        The default alias swallows connection failures so a page renders without
        its cache instead of 500ing. A throttle cannot borrow that: it decides
        from the window it reads back, and a swallowed failure reads as an empty
        window, so every caller is handed a full budget for as long as Redis is
        unwell. Raising here refuses the request instead, and the subclasses
        below inherit it — including the per-IP limit on the anonymous surfaces,
        which is the one an attacker would want gone.

        Resolved per access rather than bound at import so a test that overrides
        ``CACHES`` is honoured.
        """
        return caches["throttle"]

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


class AnonymousIPRateThrottle(AccessTokenRateThrottle):
    """Per-IP limit for the surfaces no token throttle can reach.

    ``AccessTokenRateThrottle`` keys on the resolved token row, so session and
    anonymous callers get no budget at all. That leaves the public surfaces
    (Trust Center pages, the ``auth=None`` ninja routes, the document
    access-request POST, the OIDC exchange) with no limit of any kind.

    Keying on :func:`get_client_ip` rather than ``REMOTE_ADDR`` matters: the app
    sits behind Caddy, so the peer address is the proxy for every caller and a
    single shared budget would be trivially exhausted. That helper only honours
    ``X-Real-IP`` from a trusted proxy, so the key cannot be spoofed to escape
    the limit either.

    A request that already carries a token is left to the token throttle, so an
    authenticated integration is not charged twice for one call.
    """

    cache_key_prefix = "throttle_anon_ip"

    def __init__(self, rate: str | None = None) -> None:
        super().__init__(rate or settings.API_ANONYMOUS_RATE_LIMIT)

    def get_cache_key(self, request: HttpRequest) -> str | None:
        if getattr(request, "access_token_record", None) is not None:
            return None
        from sbomify.apps.core.utils import get_client_ip

        # No usable address (REMOTE_ADDR absent under a misconfigured proxy or
        # ASGI server) must not mean "unlimited". Returning None here would skip
        # the throttle entirely, so a control meant to bound abuse would switch
        # itself off exactly when the environment is wrong. Everything
        # unidentifiable shares one bucket instead: worst case a few callers
        # contend, which is a far better failure than none being limited.
        client_ip = get_client_ip(request) or "unknown"
        return f"{self.cache_key_prefix}_{client_ip}"


class OnDemandTLSRateThrottle(AnonymousIPRateThrottle):
    """Budget for Caddy's on-demand TLS ask, separate from the public surfaces.

    The ask is issued once per TLS handshake against an unprovisioned hostname,
    so its natural rate is set by whoever is connecting rather than by anything
    sbomify does. Sharing ``AnonymousIPRateThrottle``'s bucket meant a client
    probing hostnames could spend the whole anonymous budget and take the Trust
    Center pages and the OIDC exchange down with it — and, in the other
    direction, ordinary anonymous traffic could throttle certificate issuance.
    Caddy reads any non-200 as "do not issue", so a throttled ask is a refused
    certificate.

    The distinct ``cache_key_prefix`` is what separates the two windows; without
    it this would read and write the same counter it was split off from.

    Still a per-IP limit rather than none: the route is blocked externally at
    the proxy, but a control that depends on one layer being configured
    correctly is not a control. Set well above the handshake rate a real
    workspace produces, since the decision cache in front of it already absorbs
    the repeats.
    """

    cache_key_prefix = "throttle_ondemand_tls"

    def __init__(self, rate: str | None = None) -> None:
        super().__init__(rate or settings.ON_DEMAND_TLS_RATE_LIMIT)


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

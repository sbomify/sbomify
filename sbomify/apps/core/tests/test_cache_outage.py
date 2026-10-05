"""A Redis outage should cost latency, not pages — except where it costs a limit.

django-redis re-raises connection failures out of ``cache.get``/``cache.set``
unless ``IGNORE_EXCEPTIONS`` is set. Every authenticated page renders its sidebar
and header inside ``{% cache %}``, so an unreachable or merely slow Redis turned
a page that had already done all its work into a 500.

Switching that on trades one failure for another: a rate limiter decides from the
window it reads back, and a swallowed failure reads as an empty window, so the
limit disappears for as long as Redis is unwell. The throttle therefore keeps its
own alias that still raises, and the throttle itself catches that raise and
refuses the request: a 429 with a short Retry-After, never a silent pass and
never a 500 for a request the app could not have served anyway.

Both halves are pinned here, because the pair is the point. Turning either one
round on its own is a regression the other test would not catch.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.core.cache import caches
from django.test import Client, RequestFactory, override_settings

from sbomify.apps.access_tokens.throttling import AccessTokenRateThrottle
from sbomify.apps.core.tests.shared_fixtures import (  # noqa: F401
    setup_authenticated_client_session,
)
from sbomify.apps.teams.models import Member, Team
from sbomify.settings import build_redis_caches

# A port with nothing listening: connecting fails at once rather than after the
# socket timeout, so the tests stay fast while taking the same path a timed-out
# connection takes.
_DEAD_REDIS = "redis://127.0.0.1:6399/0"


def _caches_with_redis_down() -> dict[str, dict[str, Any]]:
    """The production pair, pointed at a Redis that is not there.

    Built by the same function settings.py calls, so these tests exercise the
    real configuration rather than a copy of it that could drift.
    """
    config = build_redis_caches(_DEAD_REDIS)
    for alias in config.values():
        alias["OPTIONS"]["SOCKET_CONNECT_TIMEOUT"] = 1
        alias["OPTIONS"]["SOCKET_TIMEOUT"] = 1
    return config


@pytest.mark.django_db
def test_settings_page_renders_while_redis_is_unreachable(
    sample_team_with_owner_member: Member,  # noqa: F811
) -> None:
    """The symptom: a 500 on a page the user could otherwise see.

    Nothing on this page needs Redis to produce a correct answer. The cached
    fragments are the sidebar and header, and every other cache read on the path
    falls through to the database on a miss.
    """
    team: Team = sample_team_with_owner_member.team
    client = Client()
    client.force_login(sample_team_with_owner_member.user)
    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

    with override_settings(CACHES=_caches_with_redis_down()):
        caches.close_all()
        response = client.get(f"/workspaces/{team.key}/settings/members")

    assert response.status_code == 200


def test_throttle_refuses_rather_than_forgetting_its_window() -> None:
    """The half that must not be swallowed.

    Reading the window back is how the throttle decides. If a failed read looked
    like "no requests yet", every caller would get a fresh budget at exactly the
    moment Redis is struggling, and a caller hammering the API is one reason it
    might be. The alias the throttle uses still raises, and the throttle turns
    that raise into a refusal with a short retry hint, so the request is limited
    instead of passing unlimited and the client sees a 429 instead of a 500.
    """
    throttle = AccessTokenRateThrottle(rate="1/min")
    request = RequestFactory().get("/api/v1/whatever")
    request.access_token_record = SimpleNamespace(pk=1234)  # type: ignore[attr-defined]

    with override_settings(CACHES=_caches_with_redis_down()):
        caches.close_all()
        allowed = throttle.allow_request(request)

    # A silent True here is the failure mode this pins: an unreachable window
    # must read as "refuse and retry shortly", never as a fresh budget.
    assert allowed is False
    assert throttle.wait() == 5.0


def test_the_anonymous_ip_limit_inherits_that_refusal() -> None:
    """The per-IP limit on the public surfaces is the one worth losing least.

    It subclasses the token throttle, so it picks up the strict alias; a future
    subclass that reached for the default cache would go quiet during an outage
    on the endpoints that have no other protection.
    """
    from sbomify.apps.access_tokens.throttling import AnonymousIPRateThrottle

    throttle = AnonymousIPRateThrottle(rate="1/min")
    request = RequestFactory().get("/api/v1/public", REMOTE_ADDR="203.0.113.9")

    with override_settings(CACHES=_caches_with_redis_down()):
        caches.close_all()
        allowed = throttle.allow_request(request)

    assert allowed is False
    assert throttle.wait() == 5.0


def test_the_two_aliases_differ_in_exactly_one_option() -> None:
    """``IGNORE_EXCEPTIONS`` on default is the fix; its absence on throttle is
    the containment. Everything else about the two should stay identical, so a
    later timeout or pool change is made once and applies to both."""
    config = build_redis_caches("redis://example.test:6379/0")

    default_options = config["default"]["OPTIONS"]
    throttle_options = config["throttle"]["OPTIONS"]

    assert default_options["IGNORE_EXCEPTIONS"] is True
    assert "IGNORE_EXCEPTIONS" not in throttle_options
    assert {k: v for k, v in default_options.items() if k != "IGNORE_EXCEPTIONS"} == throttle_options
    assert config["default"]["LOCATION"] == config["throttle"]["LOCATION"]

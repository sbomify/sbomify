"""The on-demand TLS ask endpoint answers the same hostname over and over.

Caddy asks once per TLS handshake against an unprovisioned hostname, so a
client connecting in a loop turns straight into one database query per
handshake. Over 48 hours of production this endpoint was the single loudest
thing in the system: 2,935 denials and 1,184 throttled requests, together 12%
of every line the application logged, against exactly one approval.

The traffic is not spread out either — one hostname accounted for 289 denials
inside a single hour. Nothing about the answer changed between them.

The cost is not just the queries. The throttle those requests exhaust is
shared with the asks that matter, so a client hammering a hostname that will
never be approved can stop a real workspace from getting its certificate.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Team

ASK = "/api/v1/internal/domains?domain={}"


def _business_team_with_domain(domain: str) -> Team:
    team = Team.objects.create(name="Business Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.custom_domain = domain
    team.save()
    return team


@pytest.mark.django_db
class TestTheAnswerIsReused:
    def test_a_repeated_denial_queries_once(self, client, django_assert_num_queries) -> None:
        """The defect: every probe of the same hostname was a fresh lookup."""
        client.get(ASK.format("nobody.example.com"))

        with django_assert_num_queries(0):
            for _ in range(20):
                assert client.get(ASK.format("nobody.example.com")).status_code == 404

    def test_a_repeated_approval_queries_once(self, client, django_assert_num_queries) -> None:
        _business_team_with_domain("app.example.com")
        client.get(ASK.format("app.example.com"))

        with django_assert_num_queries(0):
            for _ in range(20):
                assert client.get(ASK.format("app.example.com")).status_code == 200

    def test_each_hostname_is_cached_separately(self, client) -> None:
        """A shared or truncated key would let one probe deny an unrelated
        workspace its certificate — worse than the problem being fixed."""
        _business_team_with_domain("app.example.com")

        assert client.get(ASK.format("nobody.example.com")).status_code == 404
        assert client.get(ASK.format("app.example.com")).status_code == 200


@pytest.mark.django_db
class TestTheAnswersAreStillCorrect:
    """Caching must not change any decision, only how often it is computed."""

    def test_an_allowed_domain_is_still_allowed(self, client) -> None:
        _business_team_with_domain("app.example.com")

        assert client.get(ASK.format("app.example.com")).status_code == 200

    def test_an_unknown_domain_is_still_denied(self, client) -> None:
        assert client.get(ASK.format("unknown.example.com")).status_code == 404

    def test_case_still_folds_onto_one_entry(self, client) -> None:
        """Normalisation happens before the cache lookup, so the variants share
        an entry rather than each getting their own."""
        _business_team_with_domain("app.example.com")

        assert client.get(ASK.format("APP.EXAMPLE.COM")).status_code == 200
        assert client.get(ASK.format("App.Example.Com")).status_code == 200

    def test_a_community_plan_domain_is_still_denied(self, client) -> None:
        team = Team.objects.create(name="Community Team", billing_plan="community")
        team.key = number_to_random_token(team.pk)
        team.custom_domain = "app.community.com"
        team.save()

        assert client.get(ASK.format("app.community.com")).status_code == 404


@pytest.mark.django_db
class TestTheTwoDirectionsExpireDifferently:
    """A stale denial is felt by a user waiting on their first certificate; a
    stale approval is not. The windows are set accordingly and the difference
    is the reason the constants exist, so it is worth pinning."""

    def test_denials_expire_sooner_than_approvals(self) -> None:
        from sbomify.apps.teams.apis import (
            ON_DEMAND_TLS_ALLOW_CACHE_SECONDS,
            ON_DEMAND_TLS_DENY_CACHE_SECONDS,
        )

        assert ON_DEMAND_TLS_DENY_CACHE_SECONDS < ON_DEMAND_TLS_ALLOW_CACHE_SECONDS

    def test_adding_the_domain_clears_the_denial(self, client) -> None:
        """The case the manual cache.clear() in the first version of this test
        was hiding. A customer points DNS at us before adding the domain — the
        normal order, since propagation is slow — so the hostname is probed and
        denied first. Configuring it has to take effect immediately, not after
        the deny window lapses with Caddy's own backoff on top."""
        assert client.get(ASK.format("app.example.com")).status_code == 404

        _business_team_with_domain("app.example.com")

        assert client.get(ASK.format("app.example.com")).status_code == 200

    def test_removing_the_domain_clears_the_approval(self, client) -> None:
        """The mirror case, which runs longer: an approval outlives a denial."""
        team = _business_team_with_domain("app.example.com")
        assert client.get(ASK.format("app.example.com")).status_code == 200

        team.custom_domain = None
        team.save()

        assert client.get(ASK.format("app.example.com")).status_code == 404


@pytest.mark.django_db
class TestHostileInput:
    def test_a_hostname_with_control_characters_is_denied_not_raised(self, client) -> None:
        """The hostname reaching the cache key is attacker-controlled, and some
        cache backends reject keys containing spaces or control characters. An
        unhashed key would turn a probe into a 500."""
        response = client.get(ASK.format("bad%20host%0d%0a.example.com"))

        assert response.status_code == 404

    def test_a_very_long_hostname_is_denied_not_raised(self, client) -> None:
        """Key length limits are the same hazard from the other direction."""
        response = client.get(ASK.format("a" * 500 + ".example.com"))

        assert response.status_code == 404


@pytest.mark.django_db
class TestTheAskHasItsOwnBudget:
    """The cache cannot help with this on its own.

    django-ninja charges throttles in ``Operation._run_checks()`` before the
    view runs, so a cache inside the view cannot stop the budget being spent.
    Sharing the anonymous bucket meant a client probing hostnames could exhaust
    it and take the Trust Center pages and the OIDC exchange down with it —
    while any throttled ask is a certificate Caddy then refuses to issue.
    """

    def test_the_endpoint_declares_its_own_throttle(self) -> None:
        from sbomify.apps.access_tokens.throttling import AnonymousIPRateThrottle, OnDemandTLSRateThrottle
        from sbomify.apps.teams.apis import internal_router

        operation = next(
            op
            for _path, view in internal_router.path_operations.items()
            for op in view.operations
            if "domains" in _path
        )
        throttles = list(operation.throttle_objects)

        assert any(isinstance(t, OnDemandTLSRateThrottle) for t in throttles)
        # A per-operation throttle replaces the global list, so the shared
        # anonymous limiter must not be among them or the split does nothing.
        assert not any(type(t) is AnonymousIPRateThrottle for t in throttles)

    def test_its_window_is_separate_from_the_anonymous_one(self) -> None:
        """Same key derivation, different prefix — without that they would read
        and write the same counter and the split would be cosmetic."""
        from sbomify.apps.access_tokens.throttling import AnonymousIPRateThrottle, OnDemandTLSRateThrottle

        assert OnDemandTLSRateThrottle.cache_key_prefix != AnonymousIPRateThrottle.cache_key_prefix


@pytest.mark.django_db
class TestTheRequestIsStillAttributable:
    def test_a_cache_hit_is_still_logged_with_its_source(self, client) -> None:
        """Logging behind the cache left support with no line at all for the
        handshake that failed, and no address to attribute a prober to."""
        from sbomify.apps.teams import apis as teams_apis

        client.get(ASK.format("nobody.example.com"))  # warm

        with patch.object(teams_apis.logger, "debug") as debug:
            client.get(ASK.format("nobody.example.com"))

        assert any("On-demand TLS check" in call.args[0] for call in debug.call_args_list)

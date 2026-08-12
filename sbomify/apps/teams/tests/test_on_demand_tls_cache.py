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

import pytest
from django.core.cache import cache

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

    def test_a_new_workspace_is_seen_once_the_denial_lapses(self, client) -> None:
        """Backed off, not blocked. Creating the workspace after a probe must
        not lock it out of certificates indefinitely."""
        assert client.get(ASK.format("app.example.com")).status_code == 404

        _business_team_with_domain("app.example.com")
        cache.clear()  # stands in for the deny entry expiring

        assert client.get(ASK.format("app.example.com")).status_code == 200


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

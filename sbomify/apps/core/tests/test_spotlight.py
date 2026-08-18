"""Spotlight destinations: the registry's integrity and the ranking rules.

The registry test is the important one — it fails loudly on a URL name that
does not resolve, so a typo in the JSON cannot ship as a dead palette entry.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from sbomify.apps.core.spotlight import SECTION_ORDER, load_destinations, search_destinations


class TestRegistryIntegrity:
    def test_every_destination_resolves(self):
        """A typo'd url_name would 404 a user; fail here instead."""
        unresolved = [d.url_name for d in load_destinations() if d.resolve(team_key="AAAAAAAA") is None]

        assert unresolved == []

    def test_every_section_is_known(self):
        unknown = {d.section for d in load_destinations()} - set(SECTION_ORDER)

        assert unknown == set()

    def test_every_destination_has_keywords(self):
        """The title is matched separately, so keywords exist to carry the
        words we do NOT use in the UI. An entry without them is a missed
        synonym, not a valid minimal entry."""
        bare = [d.title for d in load_destinations() if not d.keywords]

        assert bare == []

    def test_titles_are_unique_within_a_section(self):
        seen = {(d.section, d.title) for d in load_destinations()}

        assert len(seen) == len(load_destinations())

    def test_the_registry_is_not_empty(self):
        assert len(load_destinations()) > 10


class TestRanking:
    def _titles(self, query, **kwargs):
        kwargs.setdefault("role", "owner")
        kwargs.setdefault("team_key", "AAAAAAAA")
        return [r["title"] for r in search_destinations(query, **kwargs)]

    def test_a_title_prefix_leads(self):
        assert self._titles("plug")[0] == "Plugins"

    def test_a_synonym_finds_the_page_that_does_not_use_the_word(self):
        """Nothing in the UI says "api key"; someone typing it still wants
        the tokens tab."""
        assert "API tokens" in self._titles("api key")

    def test_another_synonym_path(self):
        assert "Billing" in self._titles("subscription")
        assert "Branding" in self._titles("logo")
        assert "Members" in self._titles("invite")

    def test_an_exact_title_beats_a_keyword_match(self):
        results = self._titles("billing")

        assert results[0] == "Billing"

    def test_an_empty_query_returns_nothing(self):
        assert search_destinations("") == []

    def test_results_are_stable_across_identical_queries(self):
        """A palette that reshuffles under the cursor is worse than a
        slightly worse-ranked one."""
        assert self._titles("se") == self._titles("se")

    def test_the_limit_is_honoured(self):
        assert len(search_destinations("e", role="owner", team_key="AAAAAAAA", limit=3)) == 3


class TestRoleVisibility:
    def test_a_guest_does_not_see_admin_destinations(self):
        titles = [r["title"] for r in search_destinations("token", role="guest", team_key="AAAAAAAA")]

        assert "API tokens" not in titles

    def test_an_owner_sees_owner_only_destinations(self):
        titles = [r["title"] for r in search_destinations("billing", role="owner", team_key="AAAAAAAA")]

        assert "Billing" in titles

    def test_an_admin_does_not_see_owner_only_destinations(self):
        titles = [r["title"] for r in search_destinations("billing", role="admin", team_key="AAAAAAAA")]

        assert "Billing" not in titles

    def test_a_blank_role_sees_only_unrestricted_entries(self):
        """No workspace in session is the safe default: a palette entry is a
        hint that a feature exists."""
        titles = [r["title"] for r in search_destinations("workspace", role="", team_key="AAAAAAAA")]

        assert "Workspace settings" not in titles
        assert "Switch workspace" in titles


class TestUrlBuilding:
    def _find(self, title, **kwargs):
        kwargs.setdefault("role", "owner")
        kwargs.setdefault("team_key", "AAAAAAAA")
        for result in search_destinations(title.lower(), **kwargs):
            if result["title"] == title:
                return result
        return None

    def test_a_fragment_destination_carries_its_tab(self):
        result = self._find("API tokens")

        assert result is not None
        assert result["url"].endswith("#tokens")

    def test_a_query_destination_carries_its_param(self):
        result = self._find("New product")

        assert result is not None
        assert "new=1" in result["url"]

    def test_a_team_scoped_destination_is_dropped_without_a_workspace(self):
        """Better a missing row than a link that 500s on reverse()."""
        titles = [r["title"] for r in search_destinations("supplier", role="owner", team_key="")]

        assert "Suppliers" not in titles


@pytest.mark.django_db
class TestSearchEndpoint:
    def test_destinations_outrank_a_same_named_product(self, client, sample_team_with_owner_member):
        """The whole point of the brief: navigation first, assets last."""
        from sbomify.apps.core.models import Product
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        member = sample_team_with_owner_member
        Product.objects.create(team=member.team, name="Billing")
        setup_authenticated_client_session(client, member.team, member.user)

        body = client.get(reverse("core:search"), {"q": "billing"}).json()

        assert body["results"][0]["title"] == "Billing"
        assert body["results"][0]["section"] == "settings"
        # The product is still findable, just below.
        assert any(r["section"] == "assets" for r in body["results"])

    def test_the_legacy_keys_still_populate(self, client, sample_team_with_owner_member):
        from sbomify.apps.core.models import Product
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        member = sample_team_with_owner_member
        Product.objects.create(team=member.team, name="Gateway")
        setup_authenticated_client_session(client, member.team, member.user)

        body = client.get(reverse("core:search"), {"q": "gateway"}).json()

        assert [p["name"] for p in body["products"]] == ["Gateway"]

    def test_a_short_query_returns_the_empty_shape(self, client, sample_team_with_owner_member):
        """Authenticated on purpose: the same body is what an expired session
        used to get, and the point is that these two are now different."""
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)

        response = client.get(reverse("core:search"), {"q": "a"})

        assert response.status_code == 200
        assert response.json() == {"products": [], "components": [], "results": []}


@pytest.mark.django_db
class TestWhoIsAsking:
    """A redirect cannot be followed by a fetch, so both mixins answer in JSON.

    They must not answer with the *same* JSON. An empty result set is a true
    answer for a guest and a false one for a session that just expired: it says
    the workspace is empty and hides the reason.
    """

    XHR = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def test_an_expired_session_is_told_so(self, client):
        response = client.get(reverse("core:search"), {"q": "gateway"}, **self.XHR)

        assert response.status_code == 401
        assert response.json()["authenticated"] is False
        # The shape that would have said "your workspace has nothing in it".
        assert "results" not in response.json()

    def test_a_guest_gets_an_empty_result_set(self, client, sample_team_with_owner_member):
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
        from sbomify.apps.teams.models import Member

        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)
        Member.objects.filter(pk=member.pk).update(role="guest")

        response = client.get(reverse("core:search"), {"q": "gateway"}, **self.XHR)

        assert response.status_code == 200
        assert response.json() == {"products": [], "components": [], "results": []}

    def test_a_browser_navigation_still_redirects(self, client):
        """Without the XHR header this is a page request, and a redirect to the
        login page is the right answer to it."""
        response = client.get(reverse("core:search"), {"q": "gateway"})

        assert response.status_code == 302


class TestRootLevelCoverage:
    """Every root-level page a person can reach by clicking must be reachable
    by typing — the palette is only a navigation tool if it covers the app."""

    def _titles(self, query):
        return [r["title"] for r in search_destinations(query, role="owner", team_key="AAAAAAAA")]

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("cra", "CRA Compliance"),
            ("compliance", "CRA Compliance"),
            ("trends", "Vulnerability trends"),
            ("access request", "Access requests"),
            ("nda requests", "Access requests"),
            ("my profile", "My account settings"),
            ("upgrade", "Upgrade plan"),
            ("enterprise", "Contact enterprise sales"),
        ],
    )
    def test_root_level_pages_are_reachable(self, query, expected):
        assert expected in self._titles(query)

    def test_a_shorter_title_wins_an_equal_match(self):
        """ "plug" should land on Plugins, not Plugin summary."""
        assert self._titles("plug")[0] == "Plugins"


@pytest.mark.django_db
class TestEntitySearch:
    """The "find my stuff" half: a CVE, a release, a document — the things a
    person pastes into the bar that are not pages."""

    def _search(self, client, member, q):
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        setup_authenticated_client_session(client, member.team, member.user)
        return client.get(reverse("core:search"), {"q": q}).json()["results"]

    def test_a_cve_finds_the_affected_component(self, client, sample_team_with_owner_member):
        """ "Am I affected?" is what a pasted CVE is really asking."""
        from django.utils import timezone

        from sbomify.apps.core.models import Component
        from sbomify.apps.plugins.models import VulnerabilityLifecycle

        member = sample_team_with_owner_member
        component = Component.objects.create(team=member.team, name="Gateway")
        now = timezone.now()
        VulnerabilityLifecycle.objects.create(
            component=component,
            advisory_id="CVE-2021-44228",
            severity="critical",
            first_seen_at=now,
            last_seen_at=now,
        )

        results = self._search(client, member, "CVE-2021-44228")

        assert results[0]["section"] == "findings"
        assert "Gateway" in results[0]["title"]
        assert results[0]["url"] == f"/component/{component.id}/"

    def test_a_resolved_finding_is_not_offered(self, client, sample_team_with_owner_member):
        """A closed finding is history; leading with it answers the question
        wrongly."""
        from django.utils import timezone

        from sbomify.apps.core.models import Component
        from sbomify.apps.plugins.models import VulnerabilityLifecycle

        member = sample_team_with_owner_member
        component = Component.objects.create(team=member.team, name="Fixed Gateway")
        now = timezone.now()
        VulnerabilityLifecycle.objects.create(
            component=component,
            advisory_id="CVE-2020-11111",
            severity="high",
            first_seen_at=now,
            last_seen_at=now,
            resolved_at=now,
        )

        assert self._search(client, member, "CVE-2020-11111") == []

    def test_a_release_version_is_findable(self, client, sample_team_with_owner_member):
        from sbomify.apps.core.models import Product, Release

        member = sample_team_with_owner_member
        product = Product.objects.create(team=member.team, name="Gateway Platform")
        Release.objects.create(product=product, name="v4.2.0", version="4.2.0")

        results = self._search(client, member, "4.2.0")

        assert any(r["section"] == "releases" and "Gateway Platform" in r["title"] for r in results)

    def test_an_advisory_is_findable_by_its_cve(self, client, sample_team_with_owner_member):
        from sbomify.apps.security_advisories.models import AdvisoryVulnerability, SecurityAdvisory

        member = sample_team_with_owner_member
        advisory = SecurityAdvisory.objects.create(team=member.team, title="Auth bypass")
        AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-31337")

        results = self._search(client, member, "CVE-2026-31337")

        assert any(r["section"] == "advisories" and "Auth bypass" in r["title"] for r in results)

    def test_entities_never_outrank_a_destination(self, client, sample_team_with_owner_member):
        from sbomify.apps.core.models import Product, Release

        member = sample_team_with_owner_member
        product = Product.objects.create(team=member.team, name="Zeta")
        Release.objects.create(product=product, name="billing", version="billing")

        results = self._search(client, member, "billing")

        assert results[0]["title"] == "Billing"
        assert results[0]["section"] == "settings"


@pytest.mark.django_db
class TestGuestAccess:
    """A guest must get JSON, not the mixin's HTML redirect — the client
    parses this response and would otherwise show a generic failure."""

    def test_a_guest_gets_an_empty_json_payload(self, client, sample_team_with_owner_member, guest_user):
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
        from sbomify.apps.teams.models import Member

        member = sample_team_with_owner_member
        Member.objects.create(user=guest_user, team=member.team, role="guest")
        setup_authenticated_client_session(client, member.team, guest_user)

        response = client.get(reverse("core:search"), {"q": "billing"}, headers={"x-requested-with": "XMLHttpRequest"})

        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/json")
        assert response.json() == {"products": [], "components": [], "results": []}

    def test_a_guest_page_request_still_redirects(self, client, sample_team_with_owner_member, guest_user):
        """Only the fetch path changes; a browser hitting the URL directly
        keeps the mixin's redirect."""
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
        from sbomify.apps.teams.models import Member

        member = sample_team_with_owner_member
        Member.objects.create(user=guest_user, team=member.team, role="guest")
        setup_authenticated_client_session(client, member.team, guest_user)

        response = client.get(reverse("core:search"), {"q": "billing"})

        assert response.status_code == 302


@pytest.mark.django_db
class TestUrlsAreReversed:
    """URLs come from reverse(), so a route change cannot silently produce
    dead palette links."""

    def test_asset_and_entity_urls_match_the_router(self, client, sample_team_with_owner_member):
        from sbomify.apps.core.models import Product, Release
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        member = sample_team_with_owner_member
        product = Product.objects.create(team=member.team, name="Reversed Product")
        release = Release.objects.create(product=product, name="Reversed v7.0.0", version="7.0.0")
        setup_authenticated_client_session(client, member.team, member.user)

        results = client.get(reverse("core:search"), {"q": "Reversed"}).json()["results"]
        urls = {r["url"] for r in results}

        assert reverse("core:product_details", kwargs={"product_id": product.id}) in urls
        assert reverse("core:release_details", kwargs={"product_id": product.id, "release_id": release.id}) in urls

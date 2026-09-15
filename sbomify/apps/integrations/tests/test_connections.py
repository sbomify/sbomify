"""Connection lifecycle: storing, refreshing, publishing and disconnecting."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from sbomify.apps.controls.models import ControlCatalog
from sbomify.apps.integrations import oauth
from sbomify.apps.integrations.exceptions import ProviderAuthError, ProviderUnavailable
from sbomify.apps.integrations.models import Integration
from sbomify.apps.integrations.providers.vanta import VANTA
from sbomify.apps.integrations.services import connections
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401

pytestmark = pytest.mark.django_db


def _token_set(access: str = "vat_new", refresh: str = "vrt_new", *, expires_in: int = 3600) -> oauth.TokenSet:
    return oauth.TokenSet(
        access_token=access,
        refresh_token=refresh,
        expires_at=timezone.now() + timedelta(seconds=expires_in),
        scopes=("vanta-api.all:read",),
    )


class TestSaveConnection:
    def test_stores_the_credential_and_who_connected_it(self, sample_team_with_owner_member) -> None:  # noqa: F811
        integration = connections.save_connection(
            sample_team_with_owner_member.team, VANTA, _token_set(), sample_team_with_owner_member.user
        )

        assert integration.provider == "vanta"
        assert integration.access_token == "vat_new"
        assert integration.connected_by == sample_team_with_owner_member.user
        assert integration.status == Integration.Status.CONNECTED

    def test_reconnecting_replaces_rather_than_duplicates(self, sample_team_with_owner_member) -> None:  # noqa: F811
        team = sample_team_with_owner_member.team
        connections.save_connection(team, VANTA, _token_set("vat_one"), sample_team_with_owner_member.user)
        connections.save_connection(team, VANTA, _token_set("vat_two"), sample_team_with_owner_member.user)

        assert Integration.objects.filter(team=team, provider="vanta").count() == 1
        assert Integration.objects.get(team=team, provider="vanta").access_token == "vat_two"


class TestAccessToken:
    def test_a_fresh_token_is_handed_straight_back(self, connected_vanta, monkeypatch) -> None:
        def fail(*args, **kwargs):
            raise AssertionError("should not have refreshed")

        monkeypatch.setattr(oauth, "refresh", fail)

        assert connections.access_token(connected_vanta, VANTA) == "vat_live"

    @pytest.mark.parametrize(
        "expires_at",
        [None, timezone.now() - timedelta(minutes=1), timezone.now() + timedelta(minutes=1)],
        ids=["no-expiry", "expired", "inside-the-leeway"],
    )
    def test_a_stale_token_is_rotated_and_persisted(self, connected_vanta, monkeypatch, expires_at) -> None:
        connected_vanta.token_expires_at = expires_at
        connected_vanta.save()
        monkeypatch.setattr(oauth, "refresh", lambda provider, token: _token_set("vat_rotated", "vrt_rotated"))

        assert connections.access_token(connected_vanta, VANTA) == "vat_rotated"

        connected_vanta.refresh_from_db()
        assert connected_vanta.access_token == "vat_rotated"
        # Vanta rotates the refresh token too, and the new one has to be on
        # disk before the access token is used.
        assert connected_vanta.refresh_token == "vrt_rotated"

    def test_a_reissue_with_no_new_refresh_token_keeps_the_old_one(self, connected_vanta, monkeypatch) -> None:
        connected_vanta.token_expires_at = None
        connected_vanta.save()
        monkeypatch.setattr(oauth, "refresh", lambda provider, token: _token_set("vat_rotated", ""))

        connections.access_token(connected_vanta, VANTA)

        connected_vanta.refresh_from_db()
        assert connected_vanta.refresh_token == "vrt_live"

    def test_a_refused_refresh_asks_for_a_reconnect(self, connected_vanta, monkeypatch) -> None:
        connected_vanta.token_expires_at = None
        connected_vanta.save()

        def refuse(provider, token):
            raise ProviderAuthError("refused", service="vanta")

        monkeypatch.setattr(oauth, "refresh", refuse)

        with pytest.raises(ProviderAuthError):
            connections.access_token(connected_vanta, VANTA)

        connected_vanta.refresh_from_db()
        assert connected_vanta.status == Integration.Status.REVOKED

    def test_an_unreachable_provider_leaves_the_connection_alone(self, connected_vanta, monkeypatch) -> None:
        """A 503 at the token endpoint is not a dead credential.

        Marking it revoked would stop the scheduler queueing this workspace at
        all, so one bad minute would silently end syncing until a human redid
        OAuth.
        """
        connected_vanta.token_expires_at = None
        connected_vanta.save()

        def unavailable(provider, token):
            raise ProviderUnavailable("Vanta is not answering.", service="vanta")

        monkeypatch.setattr(oauth, "refresh", unavailable)

        with pytest.raises(ProviderUnavailable):
            connections.access_token(connected_vanta, VANTA)

        connected_vanta.refresh_from_db()
        assert connected_vanta.status == Integration.Status.CONNECTED
        assert connected_vanta.refresh_token == "vrt_live"

    def test_a_connection_with_no_refresh_token_cannot_recover(self, connected_vanta) -> None:
        connected_vanta.refresh_token = ""
        connected_vanta.token_expires_at = None
        connected_vanta.save()

        with pytest.raises(ProviderAuthError):
            connections.access_token(connected_vanta, VANTA)

        connected_vanta.refresh_from_db()
        assert connected_vanta.status == Integration.Status.REVOKED


class TestConcurrentRefresh:
    def test_a_second_caller_finds_the_token_already_rotated(self, connected_vanta, monkeypatch) -> None:
        """Two callers must not both spend a refresh token the provider rotates.

        "Sync now" landing on top of the scheduled run is the real case: both
        read the same stored token, both send it, and the loser's 401 reads as
        a dead credential and revokes a working connection. The row lock turns
        the second caller into a no-op instead.
        """
        connected_vanta.token_expires_at = None
        connected_vanta.save()

        calls: list[str] = []

        def refresh_once(provider, token):
            calls.append(token)
            return _token_set("vat_rotated", "vrt_rotated")

        monkeypatch.setattr(oauth, "refresh", refresh_once)

        first = connections.access_token(connected_vanta, VANTA)
        # A second caller holding its own copy of the row, as a separate
        # process would.
        second_view = Integration.objects.get(pk=connected_vanta.pk)
        second = connections.access_token(second_view, VANTA)

        assert first == second == "vat_rotated"
        assert calls == ["vrt_live"]

    def test_the_callers_own_instance_is_brought_up_to_date(self, connected_vanta, monkeypatch) -> None:
        """The caller goes on using the object it passed in, so it must be current."""
        connected_vanta.token_expires_at = None
        connected_vanta.save()
        monkeypatch.setattr(oauth, "refresh", lambda provider, token: _token_set("vat_rotated", "vrt_rotated"))

        connections.access_token(connected_vanta, VANTA)

        assert connected_vanta.access_token == "vat_rotated"
        assert connected_vanta.refresh_token == "vrt_rotated"


@pytest.mark.django_db
class TestDisconnect:
    def test_takes_synced_frameworks_off_the_trust_center(self, connected_vanta) -> None:
        catalog = ControlCatalog.objects.create(
            team=connected_vanta.team,
            name="SOC 2 Type II",
            version="",
            source=ControlCatalog.Source.VANTA,
            external_id="fw_soc2",
            is_published=True,
        )

        assert connections.disconnect(connected_vanta.team, "vanta").ok

        catalog.refresh_from_db()
        assert catalog.is_published is False
        assert not Integration.objects.filter(id=connected_vanta.id).exists()

    def test_keeps_the_synced_data_so_a_reconnect_is_not_a_reimport(self, connected_vanta) -> None:
        ControlCatalog.objects.create(
            team=connected_vanta.team,
            name="SOC 2 Type II",
            version="",
            source=ControlCatalog.Source.VANTA,
            external_id="fw_soc2",
            is_active=True,
        )

        connections.disconnect(connected_vanta.team, "vanta")

        assert ControlCatalog.objects.filter(team=connected_vanta.team, source="vanta").exists()

    def test_leaves_hand_maintained_frameworks_published(self, connected_vanta) -> None:
        builtin = ControlCatalog.objects.create(
            team=connected_vanta.team,
            name="ISO 27001:2022",
            version="2022",
            source=ControlCatalog.Source.BUILTIN,
            is_published=True,
        )

        connections.disconnect(connected_vanta.team, "vanta")

        builtin.refresh_from_db()
        assert builtin.is_published is True

    def test_disconnecting_what_is_not_connected_is_a_404(self, sample_team_with_owner_member) -> None:  # noqa: F811
        result = connections.disconnect(sample_team_with_owner_member.team, "vanta")
        assert not result.ok
        assert result.status_code == 404


class TestPublishing:
    @pytest.fixture
    def synced_catalog(self, connected_vanta) -> ControlCatalog:
        return ControlCatalog.objects.create(
            team=connected_vanta.team,
            name="SOC 2 Type II",
            version="",
            source=ControlCatalog.Source.VANTA,
            external_id="fw_soc2",
            is_published=False,
        )

    def test_publishing_puts_a_framework_on_the_trust_center(self, connected_vanta, synced_catalog) -> None:
        result = connections.set_catalog_published(connected_vanta.team, synced_catalog.id, True)

        assert result.ok
        assert result.value == "SOC 2 Type II"
        synced_catalog.refresh_from_db()
        assert synced_catalog.is_published is True

    def test_publishing_does_not_touch_whether_it_is_tracked(self, connected_vanta, synced_catalog) -> None:
        connections.set_catalog_published(connected_vanta.team, synced_catalog.id, False)

        synced_catalog.refresh_from_db()
        assert synced_catalog.is_active is True

    def test_unpublishing_takes_it_off_again(self, connected_vanta, synced_catalog) -> None:
        synced_catalog.is_published = True
        synced_catalog.save()

        connections.set_catalog_published(connected_vanta.team, synced_catalog.id, False)

        synced_catalog.refresh_from_db()
        assert synced_catalog.is_published is False

    def test_refuses_a_framework_no_integration_owns(self, connected_vanta) -> None:
        """This endpoint publishes synced data; hand-maintained catalogues are not its business."""
        builtin = ControlCatalog.objects.create(
            team=connected_vanta.team, name="HIPAA", version="2024", source=ControlCatalog.Source.BUILTIN
        )

        result = connections.set_catalog_published(connected_vanta.team, builtin.id, True)

        assert not result.ok
        assert result.status_code == 400

    def test_refuses_a_framework_from_another_workspace(self, connected_vanta, guest_user) -> None:
        from sbomify.apps.teams.models import Team

        other_team = Team.objects.create(name="Other workspace")
        foreign = ControlCatalog.objects.create(
            team=other_team, name="SOC 2 Type II", version="", source=ControlCatalog.Source.VANTA
        )

        result = connections.set_catalog_published(connected_vanta.team, foreign.id, True)

        assert not result.ok
        assert result.status_code == 404


class TestProviderCards:
    def test_lists_every_provider_even_when_nothing_is_connected(self, sample_team_with_owner_member) -> None:  # noqa: F811
        cards = connections.provider_cards(sample_team_with_owner_member.team)

        assert [card["provider"].key for card in cards] == ["vanta"]
        assert cards[0]["is_connected"] is False
        assert cards[0]["catalogs"] == []

    def test_a_connected_card_carries_its_synced_frameworks(self, connected_vanta) -> None:
        ControlCatalog.objects.create(
            team=connected_vanta.team,
            name="SOC 2 Type II",
            version="",
            source=ControlCatalog.Source.VANTA,
            external_id="fw_soc2",
            is_published=True,
        )

        card = connections.provider_cards(connected_vanta.team)[0]

        assert card["is_connected"] is True
        assert card["needs_reconnect"] is False
        assert [catalog["name"] for catalog in card["catalogs"]] == ["SOC 2 Type II"]
        assert card["catalogs"][0]["is_published"] is True

    def test_a_revoked_connection_is_flagged_for_a_reconnect(self, connected_vanta) -> None:
        connected_vanta.status = Integration.Status.REVOKED
        connected_vanta.save()

        card = connections.provider_cards(connected_vanta.team)[0]

        assert card["needs_reconnect"] is True

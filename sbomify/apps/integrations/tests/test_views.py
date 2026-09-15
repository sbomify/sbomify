"""The Integrations tab, the connect redirect, and the OAuth callback."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.controls.models import ControlCatalog
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.integrations import oauth
from sbomify.apps.integrations.exceptions import ProviderAuthError
from sbomify.apps.integrations.models import Integration
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


def _panel_url(team) -> str:
    return reverse("integrations:panel", kwargs={"team_key": team.key})


def _token_set() -> oauth.TokenSet:
    return oauth.TokenSet(
        access_token="vat_new",
        refresh_token="vrt_new",
        expires_at=timezone.now() + timedelta(hours=1),
        scopes=("vanta-api.all:read",),
    )


@pytest.fixture
def no_queue(monkeypatch):
    """Swallow the queued sync so a view test never needs a broker."""
    from sbomify.apps.integrations import views

    queued: list[str] = []
    monkeypatch.setattr(views.sync_integration, "send", lambda integration_id: queued.append(integration_id))
    return queued


class TestPanel:
    def test_an_admin_sees_the_provider(self, admin_client_for_team, sample_team_with_owner_member) -> None:  # noqa: F811
        response = admin_client_for_team.get(_panel_url(sample_team_with_owner_member.team))

        assert response.status_code == 200
        assert b"Vanta" in response.content

    def test_a_member_may_not_open_it(self, sample_team_with_owner_member, guest_user) -> None:  # noqa: F811
        """Integrations is workspace configuration, so it is ADMINISTER like every other section."""
        team = sample_team_with_owner_member.team
        Member.objects.create(user=guest_user, team=team, role="member")
        client = Client()
        setup_authenticated_client_session(client, team, guest_user)

        response = client.get(_panel_url(team))

        assert response.status_code == 403

    def test_it_needs_a_sign_in(self, sample_team_with_owner_member) -> None:  # noqa: F811
        response = Client().get(_panel_url(sample_team_with_owner_member.team))
        assert response.status_code == 302

    @pytest.mark.usefixtures("vanta_credentials")
    def test_an_unconnected_provider_offers_to_connect(
        self, admin_client_for_team, sample_team_with_owner_member  # noqa: F811
    ) -> None:
        response = admin_client_for_team.get(_panel_url(sample_team_with_owner_member.team))

        assert b"Connect Vanta" in response.content

    def test_a_deployment_with_no_credentials_says_so(
        self, admin_client_for_team, sample_team_with_owner_member, settings  # noqa: F811
    ) -> None:
        settings.VANTA_CLIENT_ID = ""
        settings.VANTA_CLIENT_SECRET = ""

        response = admin_client_for_team.get(_panel_url(sample_team_with_owner_member.team))

        assert b"Not available here" in response.content
        assert b"Connect Vanta" not in response.content

    @pytest.mark.usefixtures("vanta_credentials")
    def test_a_connected_provider_lists_its_frameworks(self, admin_client_for_team, connected_vanta) -> None:
        ControlCatalog.objects.create(
            team=connected_vanta.team,
            name="SOC 2 Type II",
            version="",
            source=ControlCatalog.Source.VANTA,
            external_id="fw_soc2",
            is_active=True,
        )

        response = admin_client_for_team.get(_panel_url(connected_vanta.team))

        assert b"SOC 2 Type II" in response.content
        assert b"Sync now" in response.content

    def test_a_connection_survives_the_deployment_losing_its_credentials(
        self, admin_client_for_team, connected_vanta, settings
    ) -> None:
        """A workspace still has to be able to see and remove what it published."""
        settings.VANTA_CLIENT_ID = ""
        settings.VANTA_CLIENT_SECRET = ""
        ControlCatalog.objects.create(
            team=connected_vanta.team,
            name="SOC 2 Type II",
            version="",
            source=ControlCatalog.Source.VANTA,
            external_id="fw_soc2",
            is_active=True,
        )

        response = admin_client_for_team.get(_panel_url(connected_vanta.team))

        assert b"SOC 2 Type II" in response.content
        assert b"Disconnect" in response.content

    @pytest.mark.usefixtures("vanta_credentials")
    def test_a_revoked_connection_offers_a_reconnect_instead_of_a_sync(
        self, admin_client_for_team, connected_vanta
    ) -> None:
        """Syncing a dead credential cannot work, so the button says what will."""
        connected_vanta.status = Integration.Status.REVOKED
        connected_vanta.save()

        response = admin_client_for_team.get(_panel_url(connected_vanta.team))

        assert b"Reconnect" in response.content
        assert b"Sync now" not in response.content

    def test_no_credential_ever_reaches_the_page(self, admin_client_for_team, connected_vanta) -> None:
        response = admin_client_for_team.get(_panel_url(connected_vanta.team))

        assert b"vat_live" not in response.content
        assert b"vrt_live" not in response.content


class TestPanelActions:
    def test_sync_queues_a_run(self, admin_client_for_team, connected_vanta, no_queue) -> None:
        response = admin_client_for_team.post(
            _panel_url(connected_vanta.team), {"action": "sync", "provider": "vanta"}
        )

        assert response.status_code == 200
        assert no_queue == [connected_vanta.id]

    def test_sync_on_nothing_connected_is_refused(
        self, admin_client_for_team, sample_team_with_owner_member  # noqa: F811
    ) -> None:
        response = admin_client_for_team.post(
            _panel_url(sample_team_with_owner_member.team), {"action": "sync", "provider": "vanta"}
        )

        assert response["HX-Reswap"] == "none"

    def test_disconnect_removes_the_connection(self, admin_client_for_team, connected_vanta) -> None:
        response = admin_client_for_team.post(
            _panel_url(connected_vanta.team), {"action": "disconnect", "provider": "vanta"}
        )

        assert response.status_code == 200
        assert not Integration.objects.filter(id=connected_vanta.id).exists()

    def test_publish_puts_a_framework_on_the_trust_center(self, admin_client_for_team, connected_vanta) -> None:
        catalog = ControlCatalog.objects.create(
            team=connected_vanta.team,
            name="SOC 2 Type II",
            version="",
            source=ControlCatalog.Source.VANTA,
            external_id="fw_soc2",
            is_active=False,
        )

        admin_client_for_team.post(
            _panel_url(connected_vanta.team),
            {"action": "publish", "catalog_id": catalog.id, "published": "true"},
        )

        catalog.refresh_from_db()
        assert catalog.is_active is True

    def test_an_unknown_action_is_refused(self, admin_client_for_team, connected_vanta) -> None:
        response = admin_client_for_team.post(_panel_url(connected_vanta.team), {"action": "explode"})

        assert response["HX-Reswap"] == "none"

    def test_a_member_may_not_disconnect(self, connected_vanta, guest_user) -> None:
        team = connected_vanta.team
        Member.objects.create(user=guest_user, team=team, role="member")
        client = Client()
        setup_authenticated_client_session(client, team, guest_user)

        client.post(_panel_url(team), {"action": "disconnect", "provider": "vanta"})

        assert Integration.objects.filter(id=connected_vanta.id).exists()


@pytest.mark.usefixtures("vanta_credentials")
class TestConnect:
    def test_sends_the_admin_to_the_provider(
        self, admin_client_for_team, sample_team_with_owner_member  # noqa: F811
    ) -> None:
        team = sample_team_with_owner_member.team

        response = admin_client_for_team.post(
            reverse("integrations:connect", kwargs={"team_key": team.key, "provider": "vanta"})
        )

        assert response.status_code == 302
        assert response.url.startswith("https://app.vanta.example/oauth/authorize?")
        assert parse_qs(urlparse(response.url).query)["client_id"] == ["vci_test"]

    def test_an_unknown_provider_goes_back_to_settings(
        self, admin_client_for_team, sample_team_with_owner_member  # noqa: F811
    ) -> None:
        team = sample_team_with_owner_member.team

        response = admin_client_for_team.post(
            reverse("integrations:connect", kwargs={"team_key": team.key, "provider": "nope"})
        )

        assert response.status_code == 302
        assert "settings" in response.url

    def test_a_deployment_with_no_credentials_refuses(
        self, admin_client_for_team, sample_team_with_owner_member, settings  # noqa: F811
    ) -> None:
        settings.VANTA_CLIENT_ID = ""
        team = sample_team_with_owner_member.team

        response = admin_client_for_team.post(
            reverse("integrations:connect", kwargs={"team_key": team.key, "provider": "vanta"})
        )

        assert response.status_code == 302
        assert "vanta.example" not in response.url


@pytest.mark.usefixtures("vanta_credentials")
class TestCallback:
    @staticmethod
    def _start(client, team) -> str:
        client.post(reverse("integrations:connect", kwargs={"team_key": team.key, "provider": "vanta"}))
        return client.session[oauth.SESSION_KEY]["nonce"]

    def test_stores_the_connection_and_kicks_off_the_first_sync(
        self, admin_client_for_team, sample_team_with_owner_member, monkeypatch, no_queue  # noqa: F811
    ) -> None:
        team = sample_team_with_owner_member.team
        nonce = self._start(admin_client_for_team, team)
        monkeypatch.setattr(oauth, "exchange_code", lambda request, provider, code: _token_set())

        response = admin_client_for_team.get(
            reverse("integrations:callback", kwargs={"provider": "vanta"}), {"code": "vac_x", "state": nonce}
        )

        assert response.status_code == 302
        integration = Integration.objects.get(team=team, provider="vanta")
        assert integration.access_token == "vat_new"
        assert integration.connected_by == sample_team_with_owner_member.user
        assert no_queue == [integration.id]

    def test_a_forged_state_connects_nothing(
        self, admin_client_for_team, sample_team_with_owner_member, monkeypatch  # noqa: F811
    ) -> None:
        team = sample_team_with_owner_member.team
        self._start(admin_client_for_team, team)
        monkeypatch.setattr(oauth, "exchange_code", lambda *a, **k: pytest.fail("should not have exchanged"))

        admin_client_for_team.get(
            reverse("integrations:callback", kwargs={"provider": "vanta"}),
            {"code": "vac_x", "state": "not-the-nonce"},
        )

        assert not Integration.objects.filter(team=team).exists()

    def test_a_callback_in_a_browser_that_started_nothing_connects_nothing(
        self, admin_client_for_team, sample_team_with_owner_member, monkeypatch  # noqa: F811
    ) -> None:
        monkeypatch.setattr(oauth, "exchange_code", lambda *a, **k: pytest.fail("should not have exchanged"))

        admin_client_for_team.get(
            reverse("integrations:callback", kwargs={"provider": "vanta"}), {"code": "vac_x", "state": "anything"}
        )

        assert not Integration.objects.filter(team=sample_team_with_owner_member.team).exists()

    def test_a_refusal_at_the_provider_is_reported(
        self, admin_client_for_team, sample_team_with_owner_member, monkeypatch  # noqa: F811
    ) -> None:
        team = sample_team_with_owner_member.team
        nonce = self._start(admin_client_for_team, team)
        monkeypatch.setattr(oauth, "exchange_code", lambda *a, **k: pytest.fail("should not have exchanged"))

        response = admin_client_for_team.get(
            reverse("integrations:callback", kwargs={"provider": "vanta"}),
            {"error": "access_denied", "state": nonce},
        )

        assert response.status_code == 302
        assert not Integration.objects.filter(team=team).exists()

    def test_a_callback_with_no_code_connects_nothing(
        self, admin_client_for_team, sample_team_with_owner_member  # noqa: F811
    ) -> None:
        team = sample_team_with_owner_member.team
        nonce = self._start(admin_client_for_team, team)

        admin_client_for_team.get(
            reverse("integrations:callback", kwargs={"provider": "vanta"}), {"state": nonce}
        )

        assert not Integration.objects.filter(team=team).exists()

    def test_a_failed_exchange_connects_nothing(
        self, admin_client_for_team, sample_team_with_owner_member, monkeypatch  # noqa: F811
    ) -> None:
        team = sample_team_with_owner_member.team
        nonce = self._start(admin_client_for_team, team)

        def refuse(request, provider, code):
            raise ProviderAuthError("Vanta refused the connection.", service="vanta")

        monkeypatch.setattr(oauth, "exchange_code", refuse)

        response = admin_client_for_team.get(
            reverse("integrations:callback", kwargs={"provider": "vanta"}), {"code": "vac_x", "state": nonce}
        )

        assert response.status_code == 302
        assert not Integration.objects.filter(team=team).exists()

    def test_a_demotion_mid_flow_stops_the_connection(
        self, admin_client_for_team, sample_team_with_owner_member, monkeypatch  # noqa: F811
    ) -> None:
        """The consent screen can take a while, and the role is rechecked on the way back."""
        team = sample_team_with_owner_member.team
        nonce = self._start(admin_client_for_team, team)
        Member.objects.filter(team=team, user=sample_team_with_owner_member.user).update(role="member")
        monkeypatch.setattr(oauth, "exchange_code", lambda *a, **k: pytest.fail("should not have exchanged"))

        admin_client_for_team.get(
            reverse("integrations:callback", kwargs={"provider": "vanta"}), {"code": "vac_x", "state": nonce}
        )

        assert not Integration.objects.filter(team=team).exists()

    def test_it_needs_a_sign_in(self) -> None:
        response = Client().get(
            reverse("integrations:callback", kwargs={"provider": "vanta"}), {"code": "x", "state": "y"}
        )
        assert response.status_code == 302

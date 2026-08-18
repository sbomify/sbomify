"""Tests for team tokens view."""

import json
from datetime import timedelta

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.core.forms import CreateAccessTokenForm
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Member, Team


@pytest.mark.django_db
class TestTeamTokensView:
    """Test cases for TeamTokensView."""

    def test_get_requires_authentication(self, client: Client):
        """Test that GET requires authentication."""
        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": "test"}))
        assert response.status_code == 302

    def test_get_requires_team_membership(self, client: Client, sample_user: AbstractBaseUser):
        """Test that GET requires team membership."""
        client.force_login(sample_user)
        team = Team.objects.create(name="Test Team")
        # Ensure team has a key
        if not team.key:
            team.key = number_to_random_token(team.pk)
            team.save()

        # Ensure no current_team in session that would allow access
        session = client.session
        if "current_team" in session:
            del session["current_team"]
        session.save()

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        assert response.status_code in (403, 404)

    def test_get_renders_template(self, client: Client, sample_team_with_owner_member):
        """Test that GET renders the template correctly."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        assert response.status_code == 200
        assert b"Generate new token" in response.content
        assert b"Your tokens" in response.content

    def test_get_shows_existing_tokens(self, client: Client, sample_team_with_owner_member):
        """Test that GET shows existing access tokens scoped to this team."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        AccessToken.objects.create(
            user=user,
            description="Scoped Token",
            encoded_token="test_token_string",
            team=team,
        )

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        assert response.status_code == 200
        assert b"Scoped Token" in response.content

    def test_get_shows_last_used(self, client: Client, sample_team_with_owner_member):
        """The token list surfaces last_used_at: a relative time when set, 'never' when not."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        AccessToken.objects.create(
            user=user,
            description="Used Token",
            encoded_token="used_tok",
            team=team,
            last_used_at=timezone.now() - timedelta(days=2),
        )
        AccessToken.objects.create(
            user=user,
            description="Fresh Token",
            encoded_token="fresh_tok",
            team=team,
            last_used_at=None,
        )

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        body = response.content.decode()
        assert response.status_code == 200
        assert "Last used" in body
        # timesince renders the count + unit with a non-breaking space ("2\xa0days"),
        # then the component appends " ago" — match the stable tail.
        assert "days ago" in body  # the used token's relative time
        assert "never" in body  # the unused token's fallback

    def test_post_creates_token(self, client: Client, sample_team_with_owner_member):
        """Test that POST creates a new access token scoped to the team."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        initial_count = AccessToken.objects.filter(user=user).count()

        response = client.post(
            reverse("teams:team_tokens", kwargs={"team_key": team.key}),
            {"description": "New Test Token"},
        )

        assert response.status_code == 200
        assert AccessToken.objects.filter(user=user).count() == initial_count + 1
        msgs = list(get_messages(response.wsgi_request))
        assert any(m.message == "New access token created" for m in msgs)

        # Verify token is scoped to the team
        new_token = AccessToken.objects.filter(user=user, description="New Test Token").first()
        assert new_token is not None
        assert new_token.team_id == team.id

    def test_post_creates_token_with_default_full_scope(self, client: Client, sample_team_with_owner_member):
        """A token created without picking a scope is unscoped (NULL = full, legacy default)."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        client.post(
            reverse("teams:team_tokens", kwargs={"team_key": team.key}),
            {"description": "Full Token"},
        )
        tok = AccessToken.objects.get(user=user, description="Full Token")
        assert tok.scopes is None

    def test_post_creates_scoped_token(self, client: Client, sample_team_with_owner_member):
        """Picking the 'publish' scope persists the concrete action scope on the token."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        client.post(
            reverse("teams:team_tokens", kwargs={"team_key": team.key}),
            {"description": "CI Token", "scope": "publish"},
        )
        tok = AccessToken.objects.get(user=user, description="CI Token")
        assert tok.scopes == SCOPE_PRESETS["publish"]

    def test_post_invalid_form_returns_error(self, client: Client, sample_team_with_owner_member):
        """Test that POST with invalid form returns error."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        initial_count = AccessToken.objects.filter(user=user).count()

        response = client.post(
            reverse("teams:team_tokens", kwargs={"team_key": team.key}),
            {"description": ""},
        )

        assert response.status_code == 200
        assert AccessToken.objects.filter(user=user).count() == initial_count

    def test_post_shows_new_token(self, client: Client, sample_team_with_owner_member):
        """Test that POST response includes the new token."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        response = client.post(
            reverse("teams:team_tokens", kwargs={"team_key": team.key}),
            {"description": "New Token"},
        )

        assert response.status_code == 200
        token = AccessToken.objects.filter(user=user, description="New Token").first()
        assert token is not None
        assert token.encoded_token in response.content.decode()

    def test_token_listing_filtered_by_team(self, client: Client, sample_team_with_owner_member):
        """Create tokens for 2 teams, verify GET only shows current team's tokens."""
        team_a = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user

        # Create a second team
        team_b = Team.objects.create(name="Team B")
        team_b.key = number_to_random_token(team_b.pk)
        team_b.save()
        Member.objects.create(user=user, team=team_b, role="owner")

        # Create tokens for each team
        AccessToken.objects.create(user=user, description="Token A", encoded_token="token_a", team=team_a)
        AccessToken.objects.create(user=user, description="Token B", encoded_token="token_b", team=team_b)

        setup_authenticated_client_session(client, team_a, user)
        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team_a.key}))
        content = response.content.decode()

        assert "Token A" in content
        # Token B should not appear in the scoped tokens list
        # (it may appear in unscoped section only if team is null, but here it's scoped to team_b)
        assert "Token B" not in content

    def test_unscoped_tokens_shown_with_warning(self, client: Client, sample_team_with_owner_member):
        """Create unscoped token, verify the banner flags it."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        # Create an unscoped token
        AccessToken.objects.create(user=user, description="Legacy Token", encoded_token="legacy_token", team=None)

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        content = response.content.decode()

        assert response.status_code == 200
        assert "Legacy Token" in content
        assert "Unscoped" in content
        assert "Unscoped tokens detected" in content

    def test_banner_promises_no_cutover(self, client: Client, sample_team_with_owner_member):
        """docs/access-tokens.md says these stay valid until you rotate them, so
        the banner must not announce a removal nobody has scheduled."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        AccessToken.objects.create(user=user, description="Legacy Token", encoded_token="legacy_token", team=None)

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        content = response.content.decode()

        assert "deprecated" not in content.lower()
        assert "no forced cutover" in content

    def test_member_role_can_manage_own_tokens(self, client: Client, sample_team_with_owner_member):
        """``member`` reaches the tokens page — deliberately, and this test was inverted.

        It previously asserted 403, because ``role="member"`` was a value the code
        did not recognise and the tightening note here said such rows "were never
        meant to have token-management privileges". ``member`` is a real role now,
        and tokens are workspace-scoped only (``core:settings`` redirects creation
        here), so without this a member cannot obtain a credential to upload from
        CI — one of the things the role exists to do. The page is strictly
        per-user: it lists, creates and revokes only the caller's own tokens, and
        a token can never exceed its holder's role.
        """
        from django.contrib.auth import get_user_model

        team = sample_team_with_owner_member.team

        User = get_user_model()
        member_user = User.objects.create_user(username="member", email="member@example.com", password="test")
        Member.objects.create(team=team, user=member_user, role="member")

        setup_authenticated_client_session(client, team, member_user)

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        assert response.status_code == 200

    def test_guest_cannot_manage_tokens(self, client: Client, sample_team_with_owner_member):
        """Guests are external and hold no tier, so the page stays closed to them."""
        from django.contrib.auth import get_user_model

        team = sample_team_with_owner_member.team

        User = get_user_model()
        guest = User.objects.create_user(username="tokens-guest", email="tokens-guest@example.com", password="test")
        Member.objects.create(team=team, user=guest, role="guest")

        setup_authenticated_client_session(client, team, guest)

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        assert response.status_code == 403

    def test_admin_role_can_access(self, client: Client, sample_team_with_owner_member):
        """Test that admins can access tokens view."""
        from django.contrib.auth import get_user_model

        team = sample_team_with_owner_member.team

        User = get_user_model()
        admin_user = User.objects.create_user(username="admin", email="admin@example.com", password="test")
        Member.objects.create(team=team, user=admin_user, role="admin")

        setup_authenticated_client_session(client, team, admin_user)

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        assert response.status_code == 200

    def test_guest_role_cannot_access(self, client: Client, sample_team_with_owner_member):
        """Test that guests cannot access tokens view."""
        from django.contrib.auth import get_user_model

        team = sample_team_with_owner_member.team

        User = get_user_model()
        guest_user = User.objects.create_user(username="guest", email="guest@example.com", password="test")
        Member.objects.create(team=team, user=guest_user, role="guest")

        setup_authenticated_client_session(client, team, guest_user)

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        assert response.status_code == 403


class TestCreateAccessTokenFormExpiry:
    """``CreateAccessTokenForm`` exposes a selectable token TTL (#215)."""

    def test_default_expiry_is_90_days(self):
        """Omitting the choice falls back to the secure default of 90 days."""
        form = CreateAccessTokenForm({"description": "CI token"})
        assert form.is_valid(), form.errors
        assert form.expiry_delta() == timedelta(days=90)

    def test_explicit_expiry_choice_is_honoured(self):
        form = CreateAccessTokenForm({"description": "CI token", "expires_in_hours": str(30 * 24)})
        assert form.is_valid(), form.errors
        assert form.expiry_delta() == timedelta(days=30)

    def test_hour_scale_presets_survive_as_hours(self):
        """The point of the hours switch: a CI token for one run wants 12
        hours, and days would round that away."""
        form = CreateAccessTokenForm({"description": "CI token", "expires_in_hours": "12"})
        assert form.is_valid(), form.errors
        assert form.expiry_delta() == timedelta(hours=12)

    def test_a_custom_ttl_in_hours_is_honoured(self):
        form = CreateAccessTokenForm(
            {
                "description": "CI token",
                "expires_in_hours": "custom",
                "custom_expiry_value": "8",
                "custom_expiry_unit": "hours",
            }
        )
        assert form.is_valid(), form.errors
        assert form.expiry_delta() == timedelta(hours=8)

    def test_a_custom_ttl_in_days_is_honoured(self):
        form = CreateAccessTokenForm(
            {
                "description": "CI token",
                "expires_in_hours": "custom",
                "custom_expiry_value": "3",
                "custom_expiry_unit": "days",
            }
        )
        assert form.is_valid(), form.errors
        assert form.expiry_delta() == timedelta(days=3)

    def test_custom_without_a_value_is_rejected(self):
        form = CreateAccessTokenForm({"description": "CI token", "expires_in_hours": "custom"})
        assert not form.is_valid()
        assert "custom_expiry_value" in form.errors

    def test_a_rejected_value_gets_one_message_not_two(self):
        """A 0 is caught by the field's own min_value. Adding "enter how long"
        underneath it tells the user to do the thing they just did."""
        form = CreateAccessTokenForm(
            {
                "description": "CI token",
                "expires_in_hours": "custom",
                "custom_expiry_value": "0",
                "custom_expiry_unit": "hours",
            }
        )

        assert not form.is_valid()
        assert len(form.errors["custom_expiry_value"]) == 1

    def test_a_custom_ttl_beyond_a_year_is_rejected(self):
        """Past a year the row is indistinguishable from "never"; say so
        rather than pretending to honour it."""
        form = CreateAccessTokenForm(
            {
                "description": "CI token",
                "expires_in_hours": "custom",
                "custom_expiry_value": "400",
                "custom_expiry_unit": "days",
            }
        )
        assert not form.is_valid()
        assert "custom_expiry_value" in form.errors

    def test_a_zero_custom_ttl_is_rejected(self):
        form = CreateAccessTokenForm(
            {
                "description": "CI token",
                "expires_in_hours": "custom",
                "custom_expiry_value": "0",
                "custom_expiry_unit": "hours",
            }
        )
        assert not form.is_valid()

    def test_no_expiration_choice_returns_none(self):
        form = CreateAccessTokenForm({"description": "CI token", "expires_in_hours": "never"})
        assert form.is_valid(), form.errors
        assert form.expiry_delta() is None

    def test_invalid_expiry_choice_is_rejected(self):
        form = CreateAccessTokenForm({"description": "CI token", "expires_in_hours": "forever-and-ever"})
        assert not form.is_valid()
        assert "expires_in_hours" in form.errors


@pytest.mark.django_db
class TestTeamTokenExpiry:
    """Token creation persists the chosen expiry and the UI surfaces it (#215)."""

    def _post(self, client, team, data):
        return client.post(reverse("teams:team_tokens", kwargs={"team_key": team.key}), data)

    def test_post_sets_default_90_day_expiry(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        self._post(client, team, {"description": "Default expiry"})

        token = AccessToken.objects.get(user=user, description="Default expiry")
        assert token.expires_at is not None
        assert not token.is_expired
        # Assert the row's own created_at -> expires_at span is ~90 days.
        # Using the token's timestamps (not a test-side wall clock) keeps
        # this independent of how long the request/DB work takes under CI.
        assert abs((token.expires_at - token.created_at) - timedelta(days=90)) <= timedelta(minutes=1)

    def test_post_respects_chosen_expiry(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        self._post(client, team, {"description": "Short token", "expires_in_hours": str(30 * 24)})

        token = AccessToken.objects.get(user=user, description="Short token")
        assert token.expires_at is not None
        assert abs((token.expires_at - token.created_at) - timedelta(days=30)) <= timedelta(minutes=1)

    def test_post_creates_a_twelve_hour_token(self, client: Client, sample_team_with_owner_member):
        """Viktor's case: a token minted per action run, hours not days."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        self._post(client, team, {"description": "Action token", "expires_in_hours": "12"})

        token = AccessToken.objects.get(user=user, description="Action token")
        assert abs((token.expires_at - token.created_at) - timedelta(hours=12)) <= timedelta(minutes=1)

    def test_post_creates_an_arbitrary_custom_token(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        self._post(
            client,
            team,
            {
                "description": "Custom token",
                "expires_in_hours": "custom",
                "custom_expiry_value": "36",
                "custom_expiry_unit": "hours",
            },
        )

        token = AccessToken.objects.get(user=user, description="Custom token")
        assert abs((token.expires_at - token.created_at) - timedelta(hours=36)) <= timedelta(minutes=1)

    def test_post_no_expiration_leaves_null(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        self._post(client, team, {"description": "Forever token", "expires_in_hours": "never"})

        token = AccessToken.objects.get(user=user, description="Forever token")
        assert token.expires_at is None

    def test_listing_shows_expiry_date(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)
        AccessToken.objects.create(
            user=user,
            description="Expiring Token",
            encoded_token="expiring_tok",
            team=team,
            expires_at=timezone.now() + timedelta(days=30),
        )

        content = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key})).content.decode()
        assert "Expires" in content

    def test_listing_shows_never_for_unset_expiry(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)
        AccessToken.objects.create(
            user=user, description="Forever Token", encoded_token="forever_tok", team=team, expires_at=None
        )

        content = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key})).content.decode()
        assert "Never expires" in content

    def test_listing_flags_expired_token(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)
        AccessToken.objects.create(
            user=user,
            description="Dead Token",
            encoded_token="dead_tok",
            team=team,
            expires_at=timezone.now() - timedelta(days=1),
        )

        content = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key})).content.decode()
        assert "Expired" in content


@pytest.mark.django_db
class TestBulkTokenRevocation:
    """Bulk revoke + revoke-all on TeamTokensView.delete (#1061)."""

    def _url(self, team):
        return reverse("teams:team_tokens", kwargs={"team_key": team.key})

    def _tok(self, user, team, desc):
        return AccessToken.objects.create(user=user, encoded_token=f"enc-{desc}", description=desc, team=team)

    def test_bulk_revoke_selected(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)
        t1, t2, keep = (self._tok(user, team, d) for d in ("t1", "t2", "keep"))

        resp = client.delete(
            self._url(team), data=json.dumps({"token_ids": [t1.id, t2.id]}), content_type="application/json"
        )

        assert resp.status_code == 200
        assert not AccessToken.objects.filter(id__in=[t1.id, t2.id]).exists()
        assert AccessToken.objects.filter(id=keep.id).exists()

    def test_revoke_all_includes_unscoped(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)
        scoped = self._tok(user, team, "scoped")
        unscoped = AccessToken.objects.create(user=user, encoded_token="enc-leg", description="legacy", team=None)

        resp = client.delete(self._url(team), data=json.dumps({"all": True}), content_type="application/json")

        assert resp.status_code == 200
        assert not AccessToken.objects.filter(id__in=[scoped.id, unscoped.id]).exists()

    def test_foreign_id_rejected_and_nothing_deleted(self, client: Client, sample_team_with_owner_member, guest_user):
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)
        mine = self._tok(user, team, "mine")
        theirs = AccessToken.objects.create(
            user=guest_user, encoded_token="enc-theirs", description="theirs", team=None
        )

        resp = client.delete(
            self._url(team), data=json.dumps({"token_ids": [mine.id, theirs.id]}), content_type="application/json"
        )

        assert resp.status_code == 403
        # Reject wholesale: neither mine nor theirs is deleted.
        assert AccessToken.objects.filter(id__in=[mine.id, theirs.id]).count() == 2

    def test_empty_selection_is_400(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        resp = client.delete(self._url(team), data=json.dumps({"token_ids": []}), content_type="application/json")
        assert resp.status_code == 400

    def test_guest_cannot_bulk_revoke(self, client: Client, sample_team_with_owner_member):
        from django.contrib.auth import get_user_model

        team = sample_team_with_owner_member.team
        owner = sample_team_with_owner_member.user
        mine = self._tok(owner, team, "mine")

        guest = get_user_model().objects.create_user(username="g", email="g@example.com", password="x")
        Member.objects.create(team=team, user=guest, role="guest")
        setup_authenticated_client_session(client, team, guest)

        resp = client.delete(
            self._url(team), data=json.dumps({"token_ids": [mine.id]}), content_type="application/json"
        )
        assert resp.status_code == 403
        assert AccessToken.objects.filter(id=mine.id).exists()

    def test_emits_posthog_per_scoped_token(
        self, client: Client, sample_team_with_owner_member, mocker, django_capture_on_commit_callbacks
    ):
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)
        t1, t2 = self._tok(user, team, "t1"), self._tok(user, team, "t2")
        capture = mocker.patch("sbomify.apps.teams.views.team_tokens.capture_for_request")

        with django_capture_on_commit_callbacks(execute=True):
            resp = client.delete(
                self._url(team), data=json.dumps({"token_ids": [t1.id, t2.id]}), content_type="application/json"
            )

        assert resp.status_code == 200
        assert capture.call_count == 2

    def test_cannot_revoke_token_from_another_workspace(self, client: Client, sample_team_with_owner_member):
        """#1061: an owner/admin can't revoke their own token scoped to a DIFFERENT workspace
        via this workspace's endpoint (it isn't shown on this page)."""
        team_a = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        team_b = Team.objects.create(name="Team B")
        team_b.key = number_to_random_token(team_b.pk)
        team_b.save()
        token_b = AccessToken.objects.create(user=user, encoded_token="enc-b", description="b", team=team_b)
        setup_authenticated_client_session(client, team_a, user)

        resp = client.delete(
            self._url(team_a), data=json.dumps({"token_ids": [token_b.id]}), content_type="application/json"
        )

        assert resp.status_code == 403
        assert AccessToken.objects.filter(id=token_b.id).exists()

    def test_non_integer_token_ids_is_400(self, client: Client, sample_team_with_owner_member):
        """#1061: non-integer token_ids are rejected with 400 (not a 500 from the id__in cast)."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        resp = client.delete(self._url(team), data=json.dumps({"token_ids": ["abc"]}), content_type="application/json")
        assert resp.status_code == 400

    def test_all_as_non_boolean_does_not_revoke_all(self, client: Client, sample_team_with_owner_member):
        """#1061: a truthy non-boolean 'all' (e.g. the string 'true') must NOT trigger revoke-all."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)
        mine = self._tok(user, team, "mine")

        resp = client.delete(self._url(team), data=json.dumps({"all": "true"}), content_type="application/json")

        assert resp.status_code == 400  # falls through to the token_ids path, which is absent
        assert AccessToken.objects.filter(id=mine.id).exists()  # nothing revoked

    def test_non_dict_payload_is_400(self, client: Client, sample_team_with_owner_member):
        """#1061: a JSON body that isn't an object (e.g. a list) is rejected with 400, not a 500."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        resp = client.delete(self._url(team), data="[]", content_type="application/json")
        assert resp.status_code == 400

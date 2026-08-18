"""The workspace's supplier list.

Two things carry most of these: a supplier belongs to exactly one workspace and
must never be reachable from another, and duplicate vendors are the failure this
list exists to avoid, so near-duplicate names get their own cases.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Member, Supplier, Team
from sbomify.apps.teams.services.suppliers import (
    create_supplier,
    delete_supplier,
    get_supplier,
    list_suppliers,
    update_supplier,
)

pytestmark = pytest.mark.django_db


def _other_team(name: str = "Other Workspace") -> Team:
    team = Team.objects.create(name=name)
    team.key = number_to_random_token(team.pk)
    team.save(update_fields=["key"])
    return team


class TestCreating:
    def test_a_supplier_needs_only_a_name(self, sample_team):
        """A vendor is often tracked before anyone has found a contact for it,
        so requiring an email would block the first thing a user does."""
        result = create_supplier(sample_team, {"name": "Acme Components"})

        assert result.ok
        assert result.value.name == "Acme Components"
        assert result.value.contact_email == ""

    def test_a_blank_name_is_rejected(self, sample_team):
        result = create_supplier(sample_team, {"name": "   "})

        assert not result.ok
        assert result.status_code == 400

    def test_the_name_is_trimmed(self, sample_team):
        result = create_supplier(sample_team, {"name": "  Acme  "})

        assert result.value.name == "Acme"

    def test_the_same_name_twice_is_refused(self, sample_team):
        create_supplier(sample_team, {"name": "Acme"})

        result = create_supplier(sample_team, {"name": "Acme"})

        assert not result.ok

    def test_a_case_variant_is_refused_too(self, sample_team):
        """'Acme' and 'ACME' read as one vendor to a human, and a supplier list
        is exactly where the same company gets entered twice."""
        create_supplier(sample_team, {"name": "Acme"})

        result = create_supplier(sample_team, {"name": "ACME"})

        assert not result.ok

    def test_a_name_taken_in_another_workspace_is_free(self, sample_team):
        create_supplier(_other_team(), {"name": "Acme"})

        result = create_supplier(sample_team, {"name": "Acme"})

        assert result.ok


class TestScoping:
    def test_the_list_shows_only_this_workspaces_suppliers(self, sample_team):
        create_supplier(sample_team, {"name": "Ours"})
        create_supplier(_other_team(), {"name": "Theirs"})

        result = list_suppliers(sample_team)

        assert [s.name for s in result.value] == ["Ours"]

    def test_another_workspaces_supplier_reads_as_absent(self, sample_team):
        """404 rather than 403: confirming it exists would leak the other
        workspace's vendor list one id at a time."""
        theirs = create_supplier(_other_team(), {"name": "Theirs"}).value

        result = get_supplier(sample_team, theirs.id)

        assert not result.ok
        assert result.status_code == 404

    def test_it_cannot_be_updated_across_workspaces(self, sample_team):
        theirs = create_supplier(_other_team(), {"name": "Theirs"}).value

        result = update_supplier(sample_team, theirs.id, {"name": "Hijacked"})

        assert not result.ok
        theirs.refresh_from_db()
        assert theirs.name == "Theirs"

    def test_it_cannot_be_deleted_across_workspaces(self, sample_team):
        theirs = create_supplier(_other_team(), {"name": "Theirs"}).value

        result = delete_supplier(sample_team, theirs.id)

        assert not result.ok
        assert Supplier.objects.filter(pk=theirs.pk).exists()


class TestUpdating:
    def test_an_absent_key_leaves_the_field_alone(self, sample_team):
        """Otherwise editing one field from an inline control would blank the
        rest, and sending the whole object back would be the only safe edit."""
        supplier = create_supplier(
            sample_team, {"name": "Acme", "contact_email": "sbom@acme.test", "notes": "keep me"}
        ).value

        update_supplier(sample_team, supplier.id, {"contact_name": "Dana"})

        supplier.refresh_from_db()
        assert supplier.contact_name == "Dana"
        assert supplier.contact_email == "sbom@acme.test"
        assert supplier.notes == "keep me"

    def test_a_field_can_be_cleared_explicitly(self, sample_team):
        supplier = create_supplier(sample_team, {"name": "Acme", "notes": "old"}).value

        update_supplier(sample_team, supplier.id, {"notes": ""})

        supplier.refresh_from_db()
        assert supplier.notes == ""

    def test_renaming_onto_an_existing_name_is_refused(self, sample_team):
        create_supplier(sample_team, {"name": "Acme"})
        other = create_supplier(sample_team, {"name": "Globex"}).value

        result = update_supplier(sample_team, other.id, {"name": "Acme"})

        assert not result.ok

    def test_keeping_its_own_name_is_not_a_clash(self, sample_team):
        """The uniqueness check has to exclude the row being saved, or no
        supplier could ever have any other field edited."""
        supplier = create_supplier(sample_team, {"name": "Acme"}).value

        result = update_supplier(sample_team, supplier.id, {"name": "Acme", "contact_name": "Dana"})

        assert result.ok
        assert result.value.contact_name == "Dana"


class TestSearch:
    def test_it_matches_on_name(self, sample_team):
        create_supplier(sample_team, {"name": "Acme Components"})
        create_supplier(sample_team, {"name": "Globex"})

        result = list_suppliers(sample_team, "acme")

        assert [s.name for s in result.value] == ["Acme Components"]

    def test_it_matches_on_contact_email(self, sample_team):
        """A vendor is often remembered by the address someone was chasing."""
        create_supplier(sample_team, {"name": "Acme", "contact_email": "sbom@vendor.test"})
        create_supplier(sample_team, {"name": "Globex", "contact_email": "hi@globex.test"})

        result = list_suppliers(sample_team, "vendor.test")

        assert [s.name for s in result.value] == ["Acme"]


class TestApi:
    def _url(self, team: Team, suffix: str = "") -> str:
        return f"/api/v1/workspaces/{team.key}/suppliers{suffix}"

    def test_a_member_can_list(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        create_supplier(team, {"name": "Acme"})
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        response = client.get(self._url(team))

        assert response.status_code == 200
        assert [s["name"] for s in response.json()] == ["Acme"]

    def test_a_non_member_gets_403(self, client: Client, sample_team_with_owner_member, guest_user):
        team = sample_team_with_owner_member.team
        client.force_login(guest_user)

        response = client.get(self._url(team))

        assert response.status_code == 403

    def test_a_guest_gets_403(self, client: Client, sample_team_with_owner_member, guest_user):
        """Guests are Trust Center visitors; the supplier list is internal."""
        team = sample_team_with_owner_member.team
        Member.objects.create(team=team, user=guest_user, role="guest")
        setup_authenticated_client_session(client, team, guest_user)

        response = client.get(self._url(team))

        assert response.status_code == 403

    def test_creating_returns_201(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        response = client.post(
            self._url(team), data={"name": "Acme", "contact_email": "sbom@acme.test"}, content_type="application/json"
        )

        assert response.status_code == 201
        assert Supplier.objects.filter(team=team, name="Acme").exists()

    def test_a_duplicate_returns_409_not_500(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        create_supplier(team, {"name": "Acme"})
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        response = client.post(self._url(team), data={"name": "Acme"}, content_type="application/json")

        assert response.status_code in (400, 409)

    def test_deleting_returns_204(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        supplier = create_supplier(team, {"name": "Acme"}).value
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        response = client.delete(self._url(team, f"/{supplier.id}"))

        assert response.status_code == 204
        assert not Supplier.objects.filter(pk=supplier.pk).exists()

    def test_an_unknown_workspace_key_is_404(self, client: Client, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        response = client.get("/api/v1/workspaces/nosuchkey/suppliers")

        assert response.status_code == 404


def test_the_supplier_list_page_renders(client: Client, sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    create_supplier(team, {"name": "Acme Components"})
    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

    response = client.get(reverse("teams:suppliers", kwargs={"team_key": team.key}))

    assert response.status_code == 200
    assert "Acme Components" in response.content.decode()


class TestTheUrlWorkspaceIsWhatGetsAuthorized:
    """The page authorizes against the workspace in the URL, not the one in the
    session. TeamRoleRequiredMixin reads ``session["current_team"]``, so a view
    that then resolves the URL's workspace by membership alone lets an owner of
    one workspace act on another where they are only a guest.
    """

    def _setup(self, client: Client, sample_team_with_owner_member) -> Team:
        session_team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        other = _other_team("Someone Else's Workspace")
        Member.objects.create(team=other, user=user, role="guest")
        # Session says the workspace they own; the URL will say the other one.
        setup_authenticated_client_session(client, session_team, user)
        return other

    def test_a_guest_elsewhere_cannot_read_that_workspaces_suppliers(
        self, client: Client, sample_team_with_owner_member
    ):
        other = self._setup(client, sample_team_with_owner_member)
        create_supplier(other, {"name": "Their Vendor"})

        response = client.get(reverse("teams:suppliers", kwargs={"team_key": other.key}))

        assert response.status_code == 403
        assert "Their Vendor" not in response.content.decode()

    def test_a_guest_elsewhere_cannot_add_to_that_workspace(self, client: Client, sample_team_with_owner_member):
        other = self._setup(client, sample_team_with_owner_member)

        client.post(reverse("teams:suppliers", kwargs={"team_key": other.key}), {"name": "Injected"})

        assert not Supplier.objects.filter(team=other, name="Injected").exists()

    def test_a_guest_elsewhere_cannot_delete_from_that_workspace(self, client: Client, sample_team_with_owner_member):
        other = self._setup(client, sample_team_with_owner_member)
        supplier = create_supplier(other, {"name": "Their Vendor"}).value

        client.post(
            reverse("teams:suppliers", kwargs={"team_key": other.key}),
            {"action": "delete", "supplier_id": supplier.id},
        )

        assert Supplier.objects.filter(pk=supplier.pk).exists()

    def test_a_non_member_cannot_reach_another_workspace(self, client: Client, sample_team_with_owner_member):
        session_team = sample_team_with_owner_member.team
        stranger = _other_team("Unrelated Workspace")
        setup_authenticated_client_session(client, session_team, sample_team_with_owner_member.user)

        response = client.get(reverse("teams:suppliers", kwargs={"team_key": stranger.key}))

        assert response.status_code in (403, 404)


class TestTheDatabaseHoldsTheInvariant:
    """clean() reports the case-insensitive rule; the constraint has to enforce
    it. Two concurrent inserts of "Acme" and "ACME" both clear full_clean, so a
    case-sensitive constraint lets both commit."""

    def test_a_case_variant_is_rejected_at_the_database(self, sample_team):
        from django.db import IntegrityError, transaction

        Supplier.objects.create(team=sample_team, name="Acme")

        # Straight to the DB, skipping clean(), which is exactly what the losing
        # side of the race does. The savepoint is what the service layer wraps
        # the real insert in: without it the IntegrityError leaves the
        # transaction unusable and teardown fails instead of the assertion.
        with pytest.raises(IntegrityError), transaction.atomic():
            Supplier.objects.create(team=sample_team, name="ACME")

    def test_another_workspace_may_still_use_the_name(self, sample_team):
        Supplier.objects.create(team=sample_team, name="Acme")

        other = Supplier.objects.create(team=_other_team(), name="ACME")

        assert other.pk is not None

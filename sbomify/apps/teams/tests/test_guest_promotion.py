"""Retiring a trust-center access request when its holder joins the workspace.

This behaviour was written long ago in ``teams/signals.py``, which a
same-named package shadowed, so the receiver was never registered and no
promotion has ever tidied up after itself. It lives in ``signals/handlers.py``
now, and supersedes rather than deletes: ``NDASignature`` cascades off
``AccessRequest``, and the signed NDA is a record the reject and revoke paths
both take care to keep.
"""

from __future__ import annotations

import pytest

from sbomify.apps.core.authz import READ_INTERNAL
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.teams.models import Member, Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def team(db):
    return Team.objects.create(name="Promotion Workspace")


@pytest.fixture
def guest(django_user_model, team):
    user = django_user_model.objects.create_user(
        username="externalguest", email="externalguest@test.com", password="password"
    )
    return Member.objects.create(user=user, team=team, role="guest")


def _approved_request(team, user):
    return AccessRequest.objects.create(user=user, team=team, status=AccessRequest.Status.APPROVED)


@pytest.fixture
def nda_document(team):
    import hashlib

    content = b"Test NDA Content"
    return Document.objects.create(
        name="Company NDA",
        component=team.get_or_create_company_wide_component(),
        document_type=Document.DocumentType.COMPLIANCE,
        compliance_subcategory=Document.ComplianceSubcategory.NDA,
        document_filename="nda.pdf",
        content_type="application/pdf",
        file_size=len(content),
        content_hash=hashlib.sha256(content).hexdigest(),
        source="manual_upload",
        version="1.0",
    )


def _signature(access_request, nda_document):
    return NDASignature.objects.create(
        access_request=access_request,
        nda_document=nda_document,
        nda_content_hash=nda_document.content_hash,
        signed_name="External Guest",
    )


class TestPromotion:
    @pytest.mark.parametrize("role", sorted(set(READ_INTERNAL)))
    def test_every_internal_role_retires_the_request(self, team, guest, role):
        """Any internal role, not just admin and owner: a guest promoted to
        member is equally no longer an external visitor."""
        access_request = _approved_request(team, guest.user)

        guest.role = role
        guest.save()

        access_request.refresh_from_db()
        assert access_request.status == AccessRequest.Status.REVOKED
        assert access_request.revoked_at is not None

    def test_the_signed_nda_survives(self, team, guest, nda_document):
        """Deleting the request would cascade the signature away with it."""
        access_request = _approved_request(team, guest.user)
        signature = _signature(access_request, nda_document)

        guest.role = "member"
        guest.save()

        signature.refresh_from_db()
        assert signature.superseded_at is not None, "the signature should be superseded, not erased"
        assert NDASignature.objects.filter(pk=signature.pk).exists(), "the legal record must survive"

    def test_a_superseded_signature_no_longer_counts(self, team, guest, nda_document):
        """Superseding is what makes a later re-request sign again."""
        access_request = _approved_request(team, guest.user)
        _signature(access_request, nda_document)

        guest.role = "admin"
        guest.save()

        assert not NDASignature.objects.live().filter(access_request=access_request).exists()

    def test_a_guest_who_stays_a_guest_is_untouched(self, team, guest):
        access_request = _approved_request(team, guest.user)

        guest.is_default_team = True
        guest.save()

        access_request.refresh_from_db()
        assert access_request.status == AccessRequest.Status.APPROVED

    def test_a_new_internal_member_is_not_affected(self, django_user_model, team):
        """Creations are skipped: there is no promotion to react to."""
        user = django_user_model.objects.create_user(
            username="freshmember", email="freshmember@test.com", password="password"
        )

        member = Member.objects.create(user=user, team=team, role="member")

        assert member.role == "member"
        assert not AccessRequest.objects.filter(team=team, user=user).exists()

    def test_it_heals_rows_left_by_earlier_promotions(self, django_user_model, team):
        """The handler never ran before, so internal members already carry stale
        rows. It reads no history, so the next save on such a member clears it."""
        user = django_user_model.objects.create_user(
            username="alreadyinternal", email="alreadyinternal@test.com", password="password"
        )
        member = Member.objects.create(user=user, team=team, role="member")
        access_request = _approved_request(team, user)

        member.save()

        access_request.refresh_from_db()
        assert access_request.status == AccessRequest.Status.REVOKED

    def test_a_promotion_survives_a_failure_in_the_tidy_up(self, team, guest, monkeypatch):
        """The role change is the user's intent. A trust-center problem must not
        undo it."""
        import sbomify.apps.documents.access_models as access_models

        def boom(*args, **kwargs):
            raise RuntimeError("trust centre is down")

        monkeypatch.setattr(access_models.AccessRequest.objects, "filter", boom)

        guest.role = "admin"
        guest.save()

        guest.refresh_from_db()
        assert guest.role == "admin"

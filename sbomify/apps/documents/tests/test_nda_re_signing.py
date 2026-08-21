"""
Tests for NDA re-signing scenarios when NDA document is updated.

Tests cover:
- User with old NDA signature needs to re-sign when NDA is updated
- Access is denied until new NDA is signed
- Old signatures are archived, never deleted: an NDA signature is a legal record
"""

import hashlib
from unittest.mock import PropertyMock

import pytest
from django.test import RequestFactory

from sbomify.apps.core.services.access_control import _user_has_signed_current_nda, check_component_access
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Member


@pytest.fixture
def original_nda_document(team_with_business_plan):
    """Create original NDA document."""
    component = team_with_business_plan.get_or_create_company_wide_component()
    content = b"Original NDA Content v1.0"
    content_hash = hashlib.sha256(content).hexdigest()

    document = Document.objects.create(
        name="Company NDA v1.0",
        component=component,
        document_type=Document.DocumentType.COMPLIANCE,
        compliance_subcategory=Document.ComplianceSubcategory.NDA,
        document_filename="nda_v1.pdf",
        content_type="application/pdf",
        file_size=len(content),
        content_hash=content_hash,
        source="manual_upload",
        version="1.0",
    )

    team_with_business_plan.branding_info["company_nda_document_id"] = document.id
    team_with_business_plan.save()

    return document


@pytest.fixture
def updated_nda_document(team_with_business_plan, original_nda_document):
    """Create updated NDA document (new version)."""
    content = b"Updated NDA Content v2.0"
    content_hash = hashlib.sha256(content).hexdigest()

    document = Document.objects.create(
        name="Company NDA v2.0",
        component=original_nda_document.component,
        document_type=Document.DocumentType.COMPLIANCE,
        compliance_subcategory=Document.ComplianceSubcategory.NDA,
        document_filename="nda_v2.pdf",
        content_type="application/pdf",
        file_size=len(content),
        content_hash=content_hash,
        source="manual_upload",
        version="2.0",
    )

    # Update team to point to new NDA
    team_with_business_plan.branding_info["company_nda_document_id"] = document.id
    team_with_business_plan.save()

    return document


@pytest.fixture
def guest_with_old_nda_signature(team_with_business_plan, guest_user, original_nda_document):
    """Create guest member with signed old NDA."""
    Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")
    access_request = AccessRequest.objects.create(
        team=team_with_business_plan,
        user=guest_user,
        status=AccessRequest.Status.APPROVED,
    )
    NDASignature.objects.create(
        access_request=access_request,
        nda_document=original_nda_document,
        nda_content_hash=original_nda_document.content_hash,
        signed_name="Test User",
    )
    return access_request


@pytest.mark.django_db
class TestNDAReSigning:
    """Test NDA re-signing scenarios."""

    def test_user_has_signed_current_nda_returns_false_after_update(
        self, guest_with_old_nda_signature, updated_nda_document, team_with_business_plan, guest_user
    ):
        """Test that _user_has_signed_current_nda returns False after NDA is updated."""
        # User signed old NDA
        assert _user_has_signed_current_nda(guest_user, team_with_business_plan) is False

    def test_access_denied_until_new_nda_signed(
        self,
        guest_with_old_nda_signature,
        updated_nda_document,
        team_with_business_plan,
        guest_user,
    ):
        """Test that access is denied until new NDA is signed."""
        gated_component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.GATED,
        )

        factory = RequestFactory()
        request = factory.get("/")
        request.user = guest_user
        # Mock is_authenticated property
        type(request.user).is_authenticated = PropertyMock(return_value=True)

        result = check_component_access(request, gated_component)

        assert result.has_access is False
        assert result.reason == "gated_nda_re_sign_required"

    def test_access_granted_after_re_signing(
        self,
        guest_with_old_nda_signature,
        updated_nda_document,
        team_with_business_plan,
        guest_user,
    ):
        """Test that access is granted after re-signing new NDA."""
        gated_component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.GATED,
        )

        # Re-sign with new NDA (replaces old signature due to OneToOneField)
        access_request = AccessRequest.objects.get(team=team_with_business_plan, user=guest_user)
        NDASignature.objects.filter(access_request=access_request).delete()
        NDASignature.objects.create(
            access_request=access_request,
            nda_document=updated_nda_document,
            nda_content_hash=updated_nda_document.content_hash,
            signed_name="Test User",
        )

        factory = RequestFactory()
        request = factory.get("/")
        request.user = guest_user
        # Mock is_authenticated property
        type(request.user).is_authenticated = PropertyMock(return_value=True)

        result = check_component_access(request, gated_component)

        assert result.has_access is True
        assert result.reason == "gated_access_granted"

    def test_signing_a_new_version_archives_the_old_signature(
        self,
        guest_with_old_nda_signature,
        updated_nda_document,
        team_with_business_plan,
        guest_user,
        client,
        mocker,
    ):
        """An NDA signature is a legal record: re-signing must add, never delete.

        Drives the real signing view. The v1 row — name, hash, timestamp — has
        to survive the v2 signature, and the display accessor has to hand back
        the newest one so every existing consumer keeps working.
        """
        access_request = guest_with_old_nda_signature
        old_signature = NDASignature.objects.get(access_request=access_request)
        assert old_signature.nda_document.version == "1.0"
        old_hash = old_signature.nda_content_hash

        mocker.patch(
            "sbomify.apps.core.object_store.S3Client.get_document_data",
            return_value=b"Updated NDA Content v2.0",
        )
        client.force_login(guest_user)
        response = client.post(
            f"/workspace/{team_with_business_plan.key}/access-request/{access_request.id}/sign-nda",
            {"signed_name": "Test User", "consent": "on"},
        )
        assert response.status_code == 302

        signatures = NDASignature.objects.filter(access_request=access_request).order_by("signed_at")
        assert signatures.count() == 2
        assert signatures.first().nda_content_hash == old_hash
        assert signatures.first().nda_document.version == "1.0"
        assert signatures.last().nda_document.version == "2.0"

        access_request.refresh_from_db()
        assert access_request.nda_signature.nda_document.version == "2.0"

    def test_revocation_supersedes_but_preserves_the_signature(
        self, guest_with_old_nda_signature, team_with_business_plan, guest_user
    ):
        """Revoking access must invalidate the signature for flow purposes
        without destroying the record of what was agreed to."""
        from django.utils import timezone

        access_request = guest_with_old_nda_signature
        live = access_request.nda_signatures.filter(superseded_at__isnull=True)
        assert live.count() == 1

        access_request.nda_signatures.filter(superseded_at__isnull=True).update(superseded_at=timezone.now())

        # The record survives with its hash, but no longer reads as a live signature
        assert NDASignature.objects.filter(access_request=access_request).count() == 1
        assert access_request.nda_signatures.filter(superseded_at__isnull=True).count() == 0
        access_request.refresh_from_db()
        assert access_request.nda_signature is None

    def test_superseded_signature_does_not_grant_gated_access(
        self, guest_with_old_nda_signature, team_with_business_plan, guest_user, original_nda_document
    ):
        """A superseded signature must not satisfy the current-NDA access check."""
        from django.utils import timezone

        assert _user_has_signed_current_nda(guest_user, team_with_business_plan) is True
        guest_with_old_nda_signature.nda_signatures.update(superseded_at=timezone.now())
        assert _user_has_signed_current_nda(guest_user, team_with_business_plan) is False

    def test_owner_admin_no_nda_required_after_update(self, sample_user, team_with_business_plan, updated_nda_document):
        """Test that owners/admins don't need to sign NDA even after update."""
        Member.objects.get_or_create(user=sample_user, team=team_with_business_plan, defaults={"role": "owner"})

        gated_component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.GATED,
        )

        factory = RequestFactory()
        request = factory.get("/")
        request.user = sample_user
        # Mock is_authenticated property
        type(request.user).is_authenticated = PropertyMock(return_value=True)

        result = check_component_access(request, gated_component)

        assert result.has_access is True
        assert result.reason == "gated_access_granted"

    def test_guest_without_old_signature_needs_to_sign(self, team_with_business_plan, guest_user, updated_nda_document):
        """Test that guest without any signature needs to sign current NDA."""
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")
        AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED,
        )

        gated_component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.GATED,
        )

        factory = RequestFactory()
        request = factory.get("/")
        request.user = guest_user
        request.user.is_authenticated = True

        result = check_component_access(request, gated_component)

        assert result.has_access is False
        assert result.reason == "gated_nda_re_sign_required"

    def test_multiple_nda_updates(
        self, team_with_business_plan, guest_user, original_nda_document, updated_nda_document
    ):
        """Test handling of multiple NDA updates."""
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")
        access_request = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED,
        )

        # Sign v1.0
        NDASignature.objects.create(
            access_request=access_request,
            nda_document=original_nda_document,
            nda_content_hash=original_nda_document.content_hash,
            signed_name="Test User",
        )

        # Update to v2.0
        assert _user_has_signed_current_nda(guest_user, team_with_business_plan) is False

        # Sign v2.0
        NDASignature.objects.filter(access_request=access_request).delete()
        NDASignature.objects.create(
            access_request=access_request,
            nda_document=updated_nda_document,
            nda_content_hash=updated_nda_document.content_hash,
            signed_name="Test User",
        )

        assert _user_has_signed_current_nda(guest_user, team_with_business_plan) is True

        # Create v3.0
        content_v3 = b"NDA Content v3.0"
        content_hash_v3 = hashlib.sha256(content_v3).hexdigest()
        nda_v3 = Document.objects.create(
            name="Company NDA v3.0",
            component=original_nda_document.component,
            document_type=Document.DocumentType.COMPLIANCE,
            compliance_subcategory=Document.ComplianceSubcategory.NDA,
            document_filename="nda_v3.pdf",
            content_type="application/pdf",
            file_size=len(content_v3),
            content_hash=content_hash_v3,
            source="manual_upload",
            version="3.0",
        )

        team_with_business_plan.branding_info["company_nda_document_id"] = nda_v3.id
        team_with_business_plan.save()

        # Should need to sign v3.0
        assert _user_has_signed_current_nda(guest_user, team_with_business_plan) is False


@pytest.mark.django_db
def test_two_live_signatures_for_one_document_are_impossible(
    guest_with_old_nda_signature, original_nda_document, team_with_business_plan, guest_user
):
    """The database refuses a second live signature per (request, document);
    a superseded row for the same document remains legal history."""
    from django.db import IntegrityError, transaction
    from django.utils import timezone

    access_request = guest_with_old_nda_signature
    with pytest.raises(IntegrityError), transaction.atomic():
        NDASignature.objects.create(
            access_request=access_request,
            nda_document=original_nda_document,
            nda_content_hash=original_nda_document.content_hash,
            signed_name="Duplicate",
        )

    access_request.nda_signatures.live().update(superseded_at=timezone.now())
    NDASignature.objects.create(
        access_request=access_request,
        nda_document=original_nda_document,
        nda_content_hash=original_nda_document.content_hash,
        signed_name="Re-signed after revocation",
    )
    assert NDASignature.objects.filter(access_request=access_request).count() == 2

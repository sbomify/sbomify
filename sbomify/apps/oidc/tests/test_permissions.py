"""Tests for OIDC component-scope enforcement on upload endpoints.

The integration tests exercise the full request path: a real OIDC
token is exchanged for a sbomify token, then that token is used to
hit the SBOM and document upload endpoints. The scope check should
allow uploads to the BOUND component and reject everything else in
the same workspace.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from sbomify.apps.oidc.models import OIDCBinding
from sbomify.apps.oidc.permissions import (
    bound_component_id_for_request,
    is_authorised_for_component,
    request_is_oidc_authed,
)
from sbomify.apps.oidc.services import provision_bot_user_for_binding
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Team

EXCHANGE_URL = "/api/v1/auth/oidc/github/exchange"


@pytest.fixture
def bound_component(db, team_with_business_plan: Team) -> Component:
    """Component the binding will be pinned to."""
    return Component.objects.create(
        name="Bound", team=team_with_business_plan, component_type=Component.ComponentType.BOM
    )


@pytest.fixture
def other_component(db, team_with_business_plan: Team) -> Component:
    """A second component in the SAME workspace — bot must NOT be able to hit this."""
    return Component.objects.create(
        name="Other", team=team_with_business_plan, component_type=Component.ComponentType.BOM
    )


@pytest.fixture
def binding_for_bound(bound_component: Component, sample_user):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    placeholder = User.objects.create_user(username="placeholder-perm", password="x")
    binding = OIDCBinding.objects.create(
        component=bound_component,
        provider=OIDCBinding.PROVIDER_GITHUB,
        repository="acme/widget",
        repository_id=12345,
        repository_owner_id=67890,
        bot_user=placeholder,
        created_by=sample_user,
    )
    bot = provision_bot_user_for_binding(binding)
    binding.bot_user = bot
    binding.save(update_fields=["bot_user"])
    return binding


@pytest.fixture
def oidc_sbomify_token(
    github_claims_factory, mock_github_jwks, binding_for_bound, bound_component
) -> str:
    """Round-trip: mint a GitHub OIDC token, exchange for a sbomify token."""
    gh_token = github_claims_factory(repository_owner_id=67890, repository_id=12345)
    client = Client()
    response = client.post(
        EXCHANGE_URL,
        data=json.dumps({"component_id": bound_component.id}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {gh_token}",
    )
    assert response.status_code == 200, response.content
    return response.json()["access_token"]


class TestRequestPredicate:
    @pytest.mark.django_db
    def test_oidc_authed_token_detected(self, oidc_sbomify_token, mocker) -> None:
        from sbomify.apps.access_tokens.utils import get_user_and_token_record

        _, row = get_user_and_token_record(oidc_sbomify_token)
        fake_req = mocker.MagicMock()
        fake_req.access_token_record = row
        assert request_is_oidc_authed(fake_req) is True
        assert bound_component_id_for_request(fake_req) is not None

    @pytest.mark.django_db
    def test_no_token_record_treated_as_non_oidc(self, mocker) -> None:
        fake_req = mocker.MagicMock()
        fake_req.access_token_record = None
        assert request_is_oidc_authed(fake_req) is False
        # And is_authorised_for_component is a no-op (returns True) when
        # there's no OIDC scope to enforce.
        assert is_authorised_for_component(fake_req, mocker.MagicMock(id="anything")) is True

    @pytest.mark.django_db
    def test_orphan_bot_blocked(self, mocker, bound_component: Component) -> None:
        """Test-automator P1: defensive branch in
        ``bound_component_id_for_request`` — an OIDC-authed token whose
        bot user has NO ``OIDCBinding`` row (data integrity violation:
        binding deleted but token survived) must NOT grant unrestricted
        access. ``bound_component_id_for_request`` returns ``None`` in
        that case, and ``is_authorised_for_component`` is wired to
        treat ``None`` as fail-closed for any OIDC-authed request (see
        ``permissions.py``). This test pins that fail-closed behaviour
        so a future refactor that re-introduces an authorise-on-None
        path is caught by CI.
        """
        from django.contrib.auth import get_user_model

        from sbomify.apps.access_tokens.models import AccessToken
        from sbomify.apps.access_tokens.utils import TOKEN_TYPE_OIDC, create_personal_access_token

        UserModel = get_user_model()
        orphan_bot = UserModel.objects.create_user(username="orphan-bot", password="x")
        # Build an AccessToken with expires_at set (so ``request_is_oidc_authed``
        # returns True) but no OIDCBinding pointing at this user.
        from django.utils import timezone
        import datetime

        encoded = create_personal_access_token(
            orphan_bot,
            expires_at=(timezone.now() + datetime.timedelta(seconds=900)).timestamp(),
            token_type=TOKEN_TYPE_OIDC,
        )
        row = AccessToken.objects.create(
            encoded_token=encoded,
            description="orphan",
            user=orphan_bot,
            expires_at=timezone.now() + datetime.timedelta(seconds=900),
        )
        fake_req = mocker.MagicMock()
        fake_req.access_token_record = row
        # Reset cached binding lookup per fake request to avoid leaks
        # across tests (the cache is set on the request object).
        if hasattr(fake_req, "_oidc_binding_cache"):
            delattr(fake_req, "_oidc_binding_cache")
        # The bot is identified as OIDC-authed:
        assert request_is_oidc_authed(fake_req) is True
        # No binding → fail closed (defense-in-depth: an orphan bot
        # whose binding was somehow deleted without the cascade firing
        # must NOT keep component access).
        assert bound_component_id_for_request(fake_req) is None
        assert is_authorised_for_component(fake_req, bound_component) is False

    @pytest.mark.django_db
    def test_oidc_token_with_wiped_expires_at_still_scoped(
        self, mocker, bound_component: Component
    ) -> None:
        """Copilot defense-in-depth: if ``AccessToken.expires_at`` gets
        wiped on an OIDC token row (migration bug, manual tamper, partial
        cleanup race) while the user's ``OIDCBinding`` is still healthy,
        the request must still be classified as OIDC-authed and the
        component scope check must still apply.

        Before this hardening, ``request_is_oidc_authed`` looked at
        ``expires_at`` only — a wiped column silently demoted the bot
        to non-OIDC, which made ``is_authorised_for_component`` a no-op
        and let the bot reach any component the bot's workspace role
        permitted. The new OR-based check (expires_at set OR binding
        exists for user) closes that hole.
        """
        from django.contrib.auth import get_user_model

        from sbomify.apps.access_tokens.models import AccessToken

        UserModel = get_user_model()
        # Re-use the bound_component fixture's binding by attaching a
        # *new* bot user to it (avoids touching the original row's
        # invariants).
        bot = UserModel.objects.create_user(username="wiped-bot", password="x")
        from sbomify.apps.oidc.models import OIDCBinding

        OIDCBinding.objects.create(
            component=bound_component,
            provider=OIDCBinding.PROVIDER_GITHUB,
            repository="wiped/owner",
            repository_id=777,
            repository_owner_id=888,
            bot_user=bot,
        )
        # Persist a token row WITHOUT expires_at — the wiped-column case.
        row = AccessToken.objects.create(
            encoded_token="fake-no-exp",
            description="oidc-wiped",
            user=bot,
            expires_at=None,
        )
        fake_req = mocker.MagicMock()
        fake_req.access_token_record = row
        if hasattr(fake_req, "_oidc_binding_cache"):
            delattr(fake_req, "_oidc_binding_cache")
        # Wiped expires_at would have classified this as a PAT pre-fix;
        # the binding fallback now keeps it OIDC.
        assert request_is_oidc_authed(fake_req) is True
        # And scope is enforced: matches bound component, rejects others.
        assert bound_component_id_for_request(fake_req) == str(bound_component.id)
        assert is_authorised_for_component(fake_req, bound_component) is True
        other = mocker.MagicMock(id="other-component-id")
        assert is_authorised_for_component(fake_req, other) is False


class TestSBOMUploadScope:
    @pytest.mark.django_db
    def test_can_upload_to_bound_component(self, oidc_sbomify_token, bound_component) -> None:
        client = Client()
        minimal_cdx = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "metadata": {"timestamp": "2026-01-01T00:00:00Z"},
            "components": [],
        }
        response = client.post(
            f"/api/v1/sboms/artifact/cyclonedx/{bound_component.id}",
            data=json.dumps(minimal_cdx),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {oidc_sbomify_token}",
        )
        # Anything other than 403 means the permission gate passed.
        # (The actual upload may return 201, or 400 for content validation —
        # but if we got 403 we know scope rejected us.)
        assert response.status_code != 403, (
            f"Bound component upload rejected as forbidden: {response.content!r}"
        )

    @pytest.mark.django_db
    def test_cannot_upload_to_another_component_in_same_workspace(
        self, oidc_sbomify_token, other_component
    ) -> None:
        """The critical scoping property: bot can only push to the bound
        component, even though it's a Member of the whole workspace.
        """
        client = Client()
        minimal_cdx = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "metadata": {"timestamp": "2026-01-01T00:00:00Z"},
            "components": [],
        }
        response = client.post(
            f"/api/v1/sboms/artifact/cyclonedx/{other_component.id}",
            data=json.dumps(minimal_cdx),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {oidc_sbomify_token}",
        )
        assert response.status_code == 403

    @pytest.mark.django_db
    def test_spdx_endpoint_also_scoped(self, oidc_sbomify_token, other_component) -> None:
        client = Client()
        minimal_spdx = {
            "SPDXID": "SPDXRef-DOCUMENT",
            "spdxVersion": "SPDX-2.3",
            "creationInfo": {"created": "2026-01-01T00:00:00Z", "creators": ["Tool: sbomify"]},
            "name": "test",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example/doc",
        }
        response = client.post(
            f"/api/v1/sboms/artifact/spdx/{other_component.id}",
            data=json.dumps(minimal_spdx),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {oidc_sbomify_token}",
        )
        assert response.status_code == 403


class TestDocumentUploadScope:
    @pytest.mark.django_db
    def test_cannot_upload_doc_to_another_component(
        self, oidc_sbomify_token, team_with_business_plan: Team
    ) -> None:
        """Document upload path enforces the same scope rule."""
        doc_component = Component.objects.create(
            name="Other Doc",
            team=team_with_business_plan,
            component_type=Component.ComponentType.DOCUMENT,
        )
        client = Client()
        response = client.post(
            f"/api/v1/documents/?component_id={doc_component.id}&name=test",
            data=b"document content",
            content_type="text/plain",
            HTTP_AUTHORIZATION=f"Bearer {oidc_sbomify_token}",
        )
        assert response.status_code == 403


class TestNonOidcRequestsUnaffected:
    @pytest.mark.django_db
    def test_pat_user_with_admin_role_still_works(
        self, team_with_business_plan: Team, sample_user, bound_component
    ) -> None:
        """Regression: the new ``"bot"`` role in allowed_roles must not
        relax existing PAT/session permission — admins still work,
        non-members still rejected, etc.
        """
        from sbomify.apps.access_tokens.models import AccessToken
        from sbomify.apps.access_tokens.utils import create_personal_access_token

        # sample_user is an owner of team_with_business_plan via fixture
        pat = create_personal_access_token(sample_user)
        AccessToken.objects.create(
            encoded_token=pat,
            description="test PAT",
            user=sample_user,
            team=team_with_business_plan,
        )
        client = Client()
        minimal_cdx = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "metadata": {"timestamp": "2026-01-01T00:00:00Z"},
            "components": [],
        }
        response = client.post(
            f"/api/v1/sboms/artifact/cyclonedx/{bound_component.id}",
            data=json.dumps(minimal_cdx),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {pat}",
        )
        # Owner can upload anywhere in their workspace
        assert response.status_code != 403, response.content

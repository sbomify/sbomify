"""Tests for OIDC component-scope enforcement on upload endpoints.

The integration tests exercise the full request path: a real OIDC
token is exchanged for a sbomify token, then that token is used to
hit the SBOM and document upload endpoints. The scope check should
allow uploads to the BOUND component and reject everything else in
the same workspace.
"""

from __future__ import annotations

import json

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
def oidc_sbomify_token(github_claims_factory, mock_github_jwks, binding_for_bound, bound_component) -> str:
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
    def test_pat_request_does_at_most_one_binding_lookup(self, mocker) -> None:
        """Per-request cache regression: even though we no longer gate the
        binding lookup behind a renamable username prefix (round-16
        Copilot finding), the lookup MUST be memoised so callers that
        hit ``request_is_oidc_authed`` AND
        ``bound_component_id_for_request`` on the same request only pay
        for one DB round-trip.

        The cost per PAT request is a single unique-indexed lookup on
        ``OIDCBinding.bot_user_id`` — that's deliberate (the indexed
        probe is cheaper than the correctness risk a username gate
        introduces). What this test pins is that we don't accidentally
        do that lookup TWICE per request.
        """
        from django.contrib.auth import get_user_model

        from sbomify.apps.access_tokens.models import AccessToken

        UserModel = get_user_model()
        user = UserModel.objects.create_user(username="pat-user", password="x")
        row = AccessToken.objects.create(
            encoded_token="fake-pat",
            description="long-lived-pat",
            user=user,
            expires_at=None,
        )
        fake_req = mocker.MagicMock()
        fake_req.access_token_record = row
        if hasattr(fake_req, "_oidc_binding_cache"):
            delattr(fake_req, "_oidc_binding_cache")
        from sbomify.apps.oidc import models as oidc_models

        spy = mocker.spy(oidc_models.OIDCBinding.objects, "filter")
        # Both predicates hit on the same request — typical of an
        # upload endpoint that gates on ``is_authorised_for_component``.
        assert request_is_oidc_authed(fake_req) is False
        assert bound_component_id_for_request(fake_req) is None
        # Cache means the manager is called at most once across both.
        assert spy.call_count <= 1

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
        import datetime

        from django.utils import timezone

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
    def test_oidc_token_with_wiped_expires_at_still_scoped(self, mocker, bound_component: Component) -> None:
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
        # invariants). The username uses the production ``oidc-bot-…``
        # convention only to mirror what real bot rows look like —
        # ``request_is_oidc_authed`` no longer gates on the username
        # (the round-15 prefix shortcut was removed in round-16 because
        # a renameable username made it possible to silently demote a
        # bot to PAT classification). The real check is the binding
        # lookup itself, which this test exercises by wiping
        # ``expires_at``.
        from sbomify.apps.oidc.services import BOT_USERNAME_PREFIX

        bot = UserModel.objects.create_user(username=f"{BOT_USERNAME_PREFIX}wiped", password="x")
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
        assert response.status_code != 403, f"Bound component upload rejected as forbidden: {response.content!r}"

    @pytest.mark.django_db
    def test_cannot_upload_to_another_component_in_same_workspace(self, oidc_sbomify_token, other_component) -> None:
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
    def test_cannot_upload_doc_to_another_component(self, oidc_sbomify_token, team_with_business_plan: Team) -> None:
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


class TestOIDCTokenIsUploadOnly:
    """End-to-end: an OIDC-issued sbomify token has the bare minimum
    permission needed for trusted publishing — and nothing else.

    The bot user is a workspace Member at ``role="bot"``. Every endpoint
    that gates on ``["owner", "admin"]`` (component CRUD, product CRUD,
    metadata edits, …) MUST reject the bot. Only the two upload
    endpoints — which explicitly include ``"bot"`` in ``allowed_roles``
    AND check ``is_authorised_for_component`` — accept it, and only
    for the component the binding pins.

    This pins the "least privilege" property of the OIDC token end-to-end.
    A regression that adds ``"bot"`` to a non-upload endpoint's
    ``allowed_roles`` (or removes ``is_authorised_for_component`` from
    an upload endpoint) will be caught here.
    """

    _MINIMAL_CDX = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {"timestamp": "2026-01-01T00:00:00Z"},
        "components": [],
    }

    @pytest.mark.django_db
    def test_oidc_token_can_upload_sbom_to_bound_component(self, oidc_sbomify_token, bound_component) -> None:
        """Positive control: the one thing the OIDC token is for —
        uploading to its bound component — must work. Without this, a
        regression that breaks the bot role in ``allowed_roles`` would
        be hidden behind all the negative assertions below.
        """
        client = Client()
        response = client.post(
            f"/api/v1/sboms/artifact/cyclonedx/{bound_component.id}",
            data=json.dumps(self._MINIMAL_CDX),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {oidc_sbomify_token}",
        )
        # Permission gate passed; 201 on success, 400/409 if payload/duplicate
        # — anything but 403 means the bot was allowed past the role check.
        assert response.status_code != 403, response.content

    @pytest.mark.django_db
    def test_oidc_token_cannot_create_component(self, oidc_sbomify_token) -> None:
        """POST /components requires owner/admin. Bot must be 403.

        ``create_component`` derives the target workspace from the
        token's scope (``_get_user_team_id`` returns the bot's
        ``token_team``), so this exercises the bot reaching its OWN
        workspace and STILL being rejected — i.e. workspace membership
        alone is not sufficient.
        """
        client = Client()
        response = client.post(
            "/api/v1/components",
            data=json.dumps({"name": "bot-attempt"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {oidc_sbomify_token}",
        )
        assert response.status_code == 403, response.content

    @pytest.mark.django_db
    def test_oidc_token_cannot_delete_bound_component(self, oidc_sbomify_token, bound_component) -> None:
        """DELETE on the bot's OWN bound component must still be 403.

        Critical: the bot can *upload to* its bound component but must
        not be able to *destroy* it. Upload and destroy are different
        privileges; conflating them would let a compromised CI token
        nuke the artifacts it was meant to publish.
        """
        client = Client()
        response = client.delete(
            f"/api/v1/components/{bound_component.id}",
            HTTP_AUTHORIZATION=f"Bearer {oidc_sbomify_token}",
        )
        assert response.status_code == 403, response.content

    @pytest.mark.django_db
    def test_oidc_token_cannot_patch_component_metadata(self, oidc_sbomify_token, bound_component) -> None:
        """PATCH /components/{id}/metadata requires owner/admin.

        Metadata edits change how downstream consumers (SBOM-Index,
        compliance reports) interpret the artifact — strictly a human
        operation, not a publishing-bot one.
        """
        client = Client()
        response = client.patch(
            f"/api/v1/components/{bound_component.id}/metadata",
            data=json.dumps({"supplier": {"name": "evil-supplier"}}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {oidc_sbomify_token}",
        )
        assert response.status_code == 403, response.content

    @pytest.mark.django_db
    def test_oidc_token_cannot_create_product(self, oidc_sbomify_token) -> None:
        """POST /products requires owner/admin. Bot must be 403.

        Same shape as the component-create check, exercised against the
        Product endpoint to pin the property across both resource types.
        """
        client = Client()
        response = client.post(
            "/api/v1/products",
            data=json.dumps({"name": "bot-product"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {oidc_sbomify_token}",
        )
        assert response.status_code == 403, response.content

    @pytest.mark.django_db
    def test_oidc_token_cannot_upload_sbom_to_other_component(self, oidc_sbomify_token, other_component) -> None:
        """Even on the upload path itself, the bot is scope-locked to
        its bound component. ``other_component`` is in the SAME
        workspace as the binding — workspace membership alone (bot
        role) would let a non-OIDC actor reach it, but
        ``is_authorised_for_component`` adds the per-binding lock.

        Already covered by ``TestSBOMUploadScope`` above; restated here
        to assert "upload anywhere" is NOT what the bot can do.
        """
        client = Client()
        response = client.post(
            f"/api/v1/sboms/artifact/cyclonedx/{other_component.id}",
            data=json.dumps(self._MINIMAL_CDX),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {oidc_sbomify_token}",
        )
        assert response.status_code == 403, response.content


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


@pytest.fixture
def unpinned_binding_for_bound(bound_component: Component, sample_user):
    """A PRIVATE-repo binding: created UNPINNED (IDs NULL, bot provisioned).

    Models the private-repo path — sbomify couldn't read the repo's metadata
    at create time, so the immutable IDs are NULL and get pinned later from the
    first signed OIDC token at exchange.
    """
    binding = OIDCBinding.objects.create(
        component=bound_component,
        provider=OIDCBinding.PROVIDER_GITHUB,
        repository="acme/private-repo",
        repository_id=None,
        repository_owner_id=None,
        bot_user=None,
        created_by=sample_user,
    )
    bot = provision_bot_user_for_binding(binding)
    binding.bot_user = bot
    binding.save(update_fields=["bot_user"])
    return binding


class TestPrivateRepoEndToEnd:
    """Full private-repo trusted-publishing path, end to end through publish:

    an UNPINNED binding (the private repo's immutable IDs weren't readable at
    create time) is pinned from the first *signed* GitHub OIDC token at
    exchange, and that short-lived token then publishes an SBOM to the bound
    component. This is the private-repo equivalent of ``TestSBOMUploadScope``
    and the case the deferred-pinning design exists for.
    """

    @pytest.mark.django_db
    def test_private_repo_exchange_pins_then_publishes_sbom(
        self, github_claims_factory, mock_github_jwks, unpinned_binding_for_bound, bound_component
    ) -> None:
        # 1) A GitHub Actions OIDC token minted by the PRIVATE repo's workflow.
        #    It's GitHub-signed and already carries the immutable IDs.
        gh_token = github_claims_factory(repository="acme/private-repo", repository_owner_id=67890, repository_id=12345)
        client = Client()

        # 2) Exchange: matches the unpinned binding by name, pins its IDs from
        #    the token, and returns a short-lived sbomify token.
        exchange = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": bound_component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {gh_token}",
        )
        assert exchange.status_code == 200, exchange.content
        sbomify_token = exchange.json()["access_token"]

        # The binding is now pinned to the token's immutable IDs (was NULL).
        unpinned_binding_for_bound.refresh_from_db()
        assert unpinned_binding_for_bound.repository_id == 12345
        assert unpinned_binding_for_bound.repository_owner_id == 67890

        # 3) Publish: upload an SBOM with the short-lived token. Anything other
        #    than 403 means the (now-pinned) binding scoped the upload correctly
        #    — the private-repo flow works end to end.
        minimal_cdx = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "metadata": {"timestamp": "2026-01-01T00:00:00Z"},
            "components": [],
        }
        upload = client.post(
            f"/api/v1/sboms/artifact/cyclonedx/{bound_component.id}",
            data=json.dumps(minimal_cdx),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {sbomify_token}",
        )
        assert upload.status_code != 403, f"Private-repo upload after deferred pin was forbidden: {upload.content!r}"

    @pytest.mark.django_db
    def test_private_repo_token_still_scope_locked_to_bound_component(
        self, github_claims_factory, mock_github_jwks, unpinned_binding_for_bound, bound_component, other_component
    ) -> None:
        """The deferred-pinned token is scope-locked exactly like a pre-pinned
        one — it must NOT be able to publish to a different component."""
        gh_token = github_claims_factory(repository="acme/private-repo", repository_owner_id=67890, repository_id=12345)
        client = Client()
        exchange = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": bound_component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {gh_token}",
        )
        assert exchange.status_code == 200, exchange.content
        sbomify_token = exchange.json()["access_token"]

        minimal_cdx = {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1, "components": []}
        forbidden = client.post(
            f"/api/v1/sboms/artifact/cyclonedx/{other_component.id}",
            data=json.dumps(minimal_cdx),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {sbomify_token}",
        )
        assert forbidden.status_code == 403, forbidden.content

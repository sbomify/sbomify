"""The manufacturer's Sigstore signature over a CRA export bundle.

The real-bundle tests verify cosign's own v3.1.3 release signature: the bundle
published beside ``cosign-linux-amd64``, whose SHA-256 that release lists in
``cosign_checksums.txt``. Sigstore's release service account signed it keyless
through Google. The verifier runs offline on the trust root sigstore-python
ships, so no test here touches the network.
"""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sigstore.errors import TUFError
from sigstore.verify import Verifier

from sbomify.apps.compliance.models import CRAExportPackage
from sbomify.apps.compliance.services.export_service import build_export_package, get_signature_url
from sbomify.apps.compliance.services.export_signature import sign_export
from sbomify.apps.compliance.services.wizard_service import get_compliance_summary
from sbomify.apps.compliance.tests.test_export_service import (  # noqa: F401
    assessment,
    assessment_with_docs,
    product,
)
from sbomify.apps.core.tests.shared_fixtures import get_api_headers

BUNDLE_PATH = Path(__file__).parent / "test_data" / "cosign-v3.1.3-linux-amd64.sigstore.json"
SIGNED_DIGEST = "4629c757b7618056f8ddd7e2625ae9fdd94c0372a65049520bc7d9df9efc7f71"
SIGNER = "keyless@projectsigstore.iam.gserviceaccount.com"
GOOGLE = "https://accounts.google.com"


def _bundle() -> dict:
    return json.loads(BUNDLE_PATH.read_bytes())


class _Store:
    """Captures every upload by key. ``fail`` makes uploads raise."""

    def __init__(self, fail: bool = False) -> None:
        self.uploads: dict[str, bytes] = {}
        self.fail = fail

    def upload_data_as_file(self, bucket, key, data):
        if self.fail:
            raise RuntimeError("storage unavailable")
        self.uploads[key] = data

    def get_file_data(self, bucket, key):
        return b""

    def get_sbom_data(self, filename):
        return b""


@contextlib.contextmanager
def _records(logger_name: str):
    """Records from a logger under ``sbomify``, which does not propagate to caplog's root handler."""
    captured: list[logging.LogRecord] = []

    class _List(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _List(level=logging.DEBUG)
    logger = logging.getLogger(logger_name)
    logger.addHandler(handler)
    try:
        yield captured
    finally:
        logger.removeHandler(handler)


@pytest.fixture(autouse=True)
def offline_verifier():
    with patch(
        "sbomify.apps.compliance.services.export_signature._verifier",
        lambda: Verifier.production(offline=True),
    ):
        yield


@pytest.fixture
def store():
    s = _Store()
    with patch("sbomify.apps.compliance.services.export_signature.StorageClient", return_value=s):
        yield s


def _package(assessment, content_hash: str = SIGNED_DIGEST, **fields) -> CRAExportPackage:
    return CRAExportPackage.objects.create(
        assessment=assessment,
        storage_key=f"compliance/exports/{assessment.id}/{content_hash}.zip",
        content_hash=content_hash,
        manifest={"format_version": "1.2"},
        **fields,
    )


@pytest.mark.django_db
class TestSignExport:
    def test_a_real_keyless_signature_is_kept_with_its_signer(self, assessment, store, sample_user):
        package = _package(assessment)

        result = sign_export(package, bundle=_bundle(), identity=SIGNER, issuer=GOOGLE, user=sample_user)

        assert result.ok, result.error
        package.refresh_from_db()
        assert package.signed_by == SIGNER
        assert package.signed_by_issuer == GOOGLE
        # Fulcio issued the signing certificate at signing time; it lives ten minutes.
        assert package.signed_at == datetime(2026, 8, 6, 1, 3, 1, tzinfo=UTC)
        assert json.loads(store.uploads[package.storage_key + ".sigstore.json"]) == _bundle()

    def test_surrounding_whitespace_is_not_part_of_the_identity(self, assessment, store, sample_user):
        package = _package(assessment)

        result = sign_export(
            package, bundle=_bundle(), identity=f"  {SIGNER}\n", issuer=f" {GOOGLE} ", user=sample_user
        )

        assert result.ok, result.error
        package.refresh_from_db()
        assert (package.signed_by, package.signed_by_issuer) == (SIGNER, GOOGLE)

    def test_someone_else_cannot_be_named_as_the_signer(self, assessment, store, sample_user):
        package = _package(assessment)

        result = sign_export(
            package, bundle=_bundle(), identity="security@acme.test", issuer=GOOGLE, user=sample_user
        )

        assert result.status_code == 400
        assert "security@acme.test" in result.error
        assert SIGNER in result.error  # the library's reason names who did sign
        assert store.uploads == {}
        package.refresh_from_db()
        assert package.signed_by == ""

    def test_the_issuer_has_to_match_too(self, assessment, store, sample_user):
        package = _package(assessment)

        result = sign_export(
            package, bundle=_bundle(), identity=SIGNER, issuer="https://github.com/login/oauth", user=sample_user
        )

        assert result.status_code == 400
        assert store.uploads == {}

    def test_a_signature_over_other_bytes_is_refused(self, assessment, store, sample_user):
        package = _package(assessment, content_hash="0" * 64)

        result = sign_export(package, bundle=_bundle(), identity=SIGNER, issuer=GOOGLE, user=sample_user)

        assert result.status_code == 400
        assert "does not match this bundle" in result.error
        assert store.uploads == {}

    def test_a_file_that_is_not_a_bundle_is_refused(self, assessment, store, sample_user):
        package = _package(assessment)

        result = sign_export(package, bundle={"signature": "abc"}, identity=SIGNER, issuer=GOOGLE, user=sample_user)

        assert result.status_code == 400
        assert result.error.startswith("This file is not a Sigstore bundle.")

    def test_an_oversized_bundle_is_refused_before_it_is_read(self, assessment, store, sample_user):
        package = _package(assessment)
        verifier = MagicMock()

        with patch("sbomify.apps.compliance.services.export_signature._verifier", return_value=verifier):
            result = sign_export(
                package, bundle={**_bundle(), "padding": "x" * 70_000}, identity=SIGNER, issuer=GOOGLE, user=sample_user
            )

        assert result.status_code == 400
        verifier.verify_artifact.assert_not_called()

    def test_sigstore_out_of_reach_is_a_502(self, assessment, store, sample_user):
        package = _package(assessment)

        with patch(
            "sbomify.apps.compliance.services.export_signature._verifier",
            side_effect=TUFError("Failed to refresh TUF metadata"),
        ):
            result = sign_export(package, bundle=_bundle(), identity=SIGNER, issuer=GOOGLE, user=sample_user)

        assert result.status_code == 502
        assert result.error == "Could not reach Sigstore to check the signature. Try again."
        package.refresh_from_db()
        assert package.signed_by == ""

    def test_a_signed_bundle_cannot_be_signed_again(self, assessment, store, sample_user):
        package = _package(assessment, signed_by="first@acme.test", signed_by_issuer=GOOGLE)
        verifier = MagicMock()

        with patch("sbomify.apps.compliance.services.export_signature._verifier", return_value=verifier):
            result = sign_export(package, bundle=_bundle(), identity=SIGNER, issuer=GOOGLE, user=sample_user)

        assert result.status_code == 409
        verifier.verify_artifact.assert_not_called()

    def test_of_two_uploads_racing_only_the_first_is_kept(self, assessment, store, sample_user):
        package = _package(assessment)
        real = Verifier.production(offline=True)

        def verify_while_another_upload_lands(**kwargs):
            real.verify_artifact(**kwargs)
            CRAExportPackage.objects.filter(pk=package.pk).update(signed_by="first@acme.test", signed_by_issuer=GOOGLE)

        verifier = MagicMock()
        verifier.verify_artifact.side_effect = verify_while_another_upload_lands
        with patch("sbomify.apps.compliance.services.export_signature._verifier", return_value=verifier):
            result = sign_export(package, bundle=_bundle(), identity=SIGNER, issuer=GOOGLE, user=sample_user)

        assert result.status_code == 409
        assert store.uploads == {}
        package.refresh_from_db()
        assert package.signed_by == "first@acme.test"

    def test_a_storage_failure_records_nothing(self, assessment, sample_user):
        package = _package(assessment)

        with patch("sbomify.apps.compliance.services.export_signature.StorageClient", return_value=_Store(fail=True)):
            result = sign_export(package, bundle=_bundle(), identity=SIGNER, issuer=GOOGLE, user=sample_user)

        assert result.status_code == 502
        package.refresh_from_db()
        assert package.signed_by == ""

    def test_the_signature_is_audited(self, assessment, store, sample_user):
        package = _package(assessment)

        with _records("sbomify.compliance.audit") as records:
            sign_export(package, bundle=_bundle(), identity=SIGNER, issuer=GOOGLE, user=sample_user)

        events = [r for r in records if getattr(r, "event", None) == "cra.export.signed"]
        assert len(events) == 1
        assert events[0].package_id == package.id
        assert events[0].content_hash == SIGNED_DIGEST
        assert (events[0].signed_by, events[0].issuer) == (SIGNER, GOOGLE)
        assert events[0].user_id == sample_user.id


@pytest.mark.django_db
class TestExportAuditEvent:
    def test_every_export_is_audited_with_its_hash(self, assessment_with_docs, sample_user):
        with (
            patch("sbomify.apps.compliance.services.export_service.StorageClient", return_value=_Store()),
            _records("sbomify.compliance.audit") as records,
        ):
            result = build_export_package(assessment_with_docs, sample_user)

        events = [r for r in records if getattr(r, "event", None) == "cra.export.created"]
        assert len(events) == 1
        assert events[0].content_hash == result.value.content_hash
        assert events[0].package_id == result.value.id
        assert events[0].assessment_id == assessment_with_docs.id


@pytest.mark.django_db
class TestSignatureDownload:
    def test_a_signed_package_gets_its_bundle_url(self, assessment, mock_s3_client):
        package = _package(assessment, content_hash="0" * 64, signed_by=SIGNER, signed_by_issuer=GOOGLE)

        result = get_signature_url(package)

        assert result.ok
        assert result.value == "https://s3.example.com/presigned"
        call = mock_s3_client.generate_presigned_url.call_args.kwargs
        assert call["Params"]["Key"] == package.storage_key + ".sigstore.json"
        assert call["Params"]["ResponseContentType"] == "application/json"
        assert call["Params"]["ResponseContentDisposition"].endswith('-000000000000.zip.sigstore.json"')
        assert call["ExpiresIn"] == 900

    def test_an_unsigned_package_has_no_signature_url(self, assessment):
        result = get_signature_url(_package(assessment, content_hash="0" * 64))

        assert result.ok
        assert result.value is None


@pytest.mark.django_db
class TestStepFiveSummary:
    def test_the_last_export_names_its_file_and_signer(self, assessment):
        package = _package(
            assessment,
            signed_by=SIGNER,
            signed_by_issuer=GOOGLE,
            signed_at=datetime(2026, 8, 6, 1, 3, 1, tzinfo=UTC),
        )

        last = get_compliance_summary(assessment).value["last_export"]

        assert last["id"] == package.id
        assert last["file_name"] == f"cra-package-export-test-product-{SIGNED_DIGEST[:12]}.zip"
        assert last["signature"] == {"signed_by": SIGNER, "issuer": GOOGLE, "signed_at": "2026-08-06T01:03:01+00:00"}

    def test_an_unsigned_export_has_no_signature(self, assessment):
        _package(assessment)

        assert get_compliance_summary(assessment).value["last_export"]["signature"] is None


@pytest.mark.django_db
class TestSignatureApi:
    def _url(self, assessment, package) -> str:
        return f"/api/v1/compliance/cra/{assessment.id}/export/{package.id}/signature"

    def _post(self, client, url, token, **body):
        payload = {"bundle": _bundle(), "identity": SIGNER, "issuer": GOOGLE, **body}
        return client.post(url, data=json.dumps(payload), content_type="application/json", **get_api_headers(token))

    def test_an_owner_uploads_a_signature(self, settings, authenticated_api_client, assessment, store):
        settings.BILLING = False
        package = _package(assessment)
        client, token = authenticated_api_client

        response = self._post(client, self._url(assessment, package), token)

        assert response.status_code == 201, response.content
        assert response.json() == {"signed_by": SIGNER, "issuer": GOOGLE, "signed_at": "2026-08-06T01:03:01Z"}

    def test_the_download_endpoint_offers_the_signature_once_signed(
        self, settings, authenticated_api_client, assessment, mock_s3_client
    ):
        settings.BILLING = False
        package = _package(assessment, signed_by=SIGNER, signed_by_issuer=GOOGLE)
        client, token = authenticated_api_client

        response = client.get(
            f"/api/v1/compliance/cra/{assessment.id}/export/{package.id}/download", **get_api_headers(token)
        )

        assert response.status_code == 200
        assert response.json()["signature_url"] == "https://s3.example.com/presigned"

    def test_a_wrong_signer_is_a_400_with_the_reason(self, settings, authenticated_api_client, assessment, store):
        settings.BILLING = False
        package = _package(assessment)
        client, token = authenticated_api_client

        response = self._post(client, self._url(assessment, package), token, identity="security@acme.test")

        assert response.status_code == 400
        assert "security@acme.test" in response.json()["error"]

    def test_an_empty_identity_is_refused(self, settings, authenticated_api_client, assessment, store):
        settings.BILLING = False
        package = _package(assessment)
        client, token = authenticated_api_client

        response = self._post(client, self._url(assessment, package), token, identity="")

        assert response.status_code in (400, 422)
        package.refresh_from_db()
        assert package.signed_by == ""

    def test_a_package_of_another_assessment_is_404(self, settings, authenticated_api_client, assessment, store):
        settings.BILLING = False
        package = _package(assessment)
        client, token = authenticated_api_client

        response = self._post(client, f"/api/v1/compliance/cra/{assessment.id}/export/nope/signature", token)

        assert response.status_code == 404
        package.refresh_from_db()
        assert package.signed_by == ""

    def test_a_member_cannot_sign(self, settings, sample_team_with_owner_member, assessment, store):
        from django.test import Client

        from sbomify.apps.access_tokens.models import AccessToken
        from sbomify.apps.access_tokens.utils import create_personal_access_token
        from sbomify.apps.core.models import User
        from sbomify.apps.teams.models import Member

        settings.BILLING = False
        package = _package(assessment)
        member = User.objects.create_user(username="member_in_team", email="member@acme.test", password="x")
        Member.objects.create(user=member, team=sample_team_with_owner_member.team, role="member")
        token = AccessToken.objects.create(
            user=member, encoded_token=create_personal_access_token(member), description="member-token"
        )

        response = self._post(Client(), self._url(assessment, package), token)

        assert response.status_code == 403
        package.refresh_from_db()
        assert package.signed_by == ""


@pytest.mark.django_db
class TestExportSummaryApi:
    """One package's summary, so a page signs the ZIP it downloaded and not the newest one."""

    def _get(self, client, token, assessment, package_id: str):
        return client.get(f"/api/v1/compliance/cra/{assessment.id}/export/{package_id}", **get_api_headers(token))

    def test_it_describes_the_package_asked_for_not_the_newest(self, settings, authenticated_api_client, assessment):
        settings.BILLING = False
        mine = _package(assessment)
        _package(assessment, content_hash="b" * 64, signed_by=SIGNER, signed_by_issuer=GOOGLE)
        client, token = authenticated_api_client

        response = self._get(client, token, assessment, mine.id)

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["id"] == mine.id
        assert body["file_name"] == f"cra-package-export-test-product-{SIGNED_DIGEST[:12]}.zip"
        assert body["signature"] is None

    def test_a_package_of_another_assessment_is_404(
        self, settings, authenticated_api_client, assessment, sample_team_with_owner_member, sample_user
    ):
        from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
        from sbomify.apps.core.models import Product

        settings.BILLING = False
        team = sample_team_with_owner_member.team
        other_product = Product.objects.create(name="Other Product", team=team)
        other = get_or_create_assessment(other_product.id, sample_user, team).value
        theirs = _package(other)
        client, token = authenticated_api_client

        response = self._get(client, token, assessment, theirs.id)

        assert response.status_code == 404

    def test_a_member_is_refused_like_the_download(self, settings, sample_team_with_owner_member, assessment):
        from django.test import Client

        from sbomify.apps.access_tokens.models import AccessToken
        from sbomify.apps.access_tokens.utils import create_personal_access_token
        from sbomify.apps.core.models import User
        from sbomify.apps.teams.models import Member

        settings.BILLING = False
        package = _package(assessment)
        member = User.objects.create_user(username="member_reader", email="reader@acme.test", password="x")
        Member.objects.create(user=member, team=sample_team_with_owner_member.team, role="member")
        token = AccessToken.objects.create(
            user=member, encoded_token=create_personal_access_token(member), description="member-token"
        )

        summary = self._get(Client(), token, assessment, package.id)
        download = Client().get(
            f"/api/v1/compliance/cra/{assessment.id}/export/{package.id}/download", **get_api_headers(token)
        )

        assert summary.status_code == download.status_code == 403


@pytest.mark.django_db
class TestStepFivePage:
    """Driven through the real URL: the signer has to survive the summary, the step context and the template."""

    def _html(self, assessment, member) -> str:
        from django.test import Client
        from django.urls import reverse

        from sbomify.apps.billing.models import BillingPlan
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        team = member.team
        team.billing_plan = sorted(BillingPlan.CRA_ELIGIBLE_PLAN_KEYS)[0]
        team.save(update_fields=["billing_plan"])
        client = Client()
        client.force_login(member.user)
        setup_authenticated_client_session(client, team, member.user)
        response = client.get(reverse("compliance:cra_step", kwargs={"assessment_id": assessment.id, "step": 5}))
        assert response.status_code == 200
        return response.content.decode()

    def test_an_unsigned_export_offers_the_upload_form(self, assessment, sample_team_with_owner_member):
        _package(assessment)

        html = self._html(assessment, sample_team_with_owner_member)

        assert 'data-testid="signature-upload-form"' in html
        assert 'id="signature-file"' in html
        assert 'id="signature-identity"' in html
        assert 'id="signature-issuer"' in html
        assert "sbomify keeps no signing key." in html
        assert f'"file_name": "cra-package-export-test-product-{SIGNED_DIGEST[:12]}.zip"' in html
        assert '"signature": null' in html

    def test_a_signed_export_hands_the_page_its_signer(self, assessment, sample_team_with_owner_member):
        _package(
            assessment, signed_by=SIGNER, signed_by_issuer=GOOGLE, signed_at=datetime(2026, 8, 6, 1, 3, 1, tzinfo=UTC)
        )

        html = self._html(assessment, sample_team_with_owner_member)

        assert f'"signed_by": "{SIGNER}"' in html
        assert 'x-text="lastExport.signature.signed_by"' in html
        assert 'x-text="issuerLabel(lastExport.signature.issuer)"' in html
        assert 'x-text="verifyCommand"' in html
        assert 'data-testid="download-signature-btn"' in html

"""The signature chip on the artifact page says whether the signature holds.

It used to read the presence of the stored file, so a bundle for different
bytes, or one the verifier could not load, still showed a green "Signed".
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk.enums import RunReason
from sbomify.apps.plugins.services.signature_status import get_signature_status
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member

SIGNER = "https://github.com/acme/widget/.github/workflows/release.yml@refs/tags/v1.0.0"


def _result(status: str) -> dict[str, Any]:
    return {
        "summary": {"total_findings": 1},
        "findings": [
            {
                "id": "verification:signature-valid",
                "title": "t",
                "status": status,
                "severity": "info",
                "metadata": {"identity": SIGNER, "issuer": "https://token.actions.githubusercontent.com"},
            }
        ],
    }


def _run(sbom: SBOM, status: str = "completed", result: dict[str, Any] | None = None) -> AssessmentRun:
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="sbom-verification",
        plugin_version="2.1.0",
        plugin_config_hash=sha256(b"sbom-verification").hexdigest(),
        category="attestation",
        run_reason=RunReason.ON_UPLOAD.value,
        status=status,
        result=result,
    )


@pytest.mark.django_db
class TestSignatureChip:
    @pytest.fixture
    def page(self, sample_team_with_owner_member: Member) -> tuple[Client, Component, SBOM]:
        component = Component.objects.create(
            team=sample_team_with_owner_member.team, name="widget", component_type=Component.ComponentType.BOM
        )
        sbom = SBOM.objects.create(
            component=component,
            name="widget",
            format="cyclonedx",
            format_version="1.6",
            version="1.0",
            sbom_filename="x.json",
            signature_blob_key="x.sig",
            signature_type="cosign-bundle",
        )
        client = Client()
        setup_authenticated_client_session(
            client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
        )
        return client, component, sbom

    @staticmethod
    def _html(client: Client, component: Component, sbom: SBOM) -> str:
        url = reverse(
            "core:component_item", kwargs={"component_id": component.id, "item_type": "sboms", "item_id": sbom.id}
        )
        response = client.get(url)
        assert response.status_code == 200
        return response.content.decode()

    @pytest.mark.parametrize(
        ("finding_status", "chip"),
        [("pass", ">Signed<"), ("fail", ">Signature invalid<"), ("warning", ">Signature not verified<")],
    )
    def test_chip_follows_the_check(self, page: tuple[Client, Component, SBOM], finding_status: str, chip: str) -> None:
        client, component, sbom = page
        _run(sbom, result=_result(finding_status))

        html = self._html(client, component, sbom)

        assert chip in html
        if finding_status != "pass":
            assert ">Signed<" not in html

    def test_verified_chip_names_the_signer(self, page: tuple[Client, Component, SBOM]) -> None:
        client, component, sbom = page
        _run(sbom, result=_result("pass"))

        assert f'title="Signed by {SIGNER}' in self._html(client, component, sbom)

    def test_no_check_yet(self, page: tuple[Client, Component, SBOM]) -> None:
        client, component, sbom = page

        html = self._html(client, component, sbom)

        assert ">Signature not verified<" in html
        assert ">Signed<" not in html

    def test_a_newer_run_in_flight_is_checking(self, page: tuple[Client, Component, SBOM]) -> None:
        client, component, sbom = page
        _run(sbom, result=_result("fail"))
        _run(sbom, status="pending")

        assert ">Checking signature<" in self._html(client, component, sbom)

    def test_no_signature_no_chip(self, page: tuple[Client, Component, SBOM]) -> None:
        client, component, sbom = page
        SBOM.objects.filter(pk=sbom.pk).update(signature_blob_key="")

        html = self._html(client, component, sbom)

        for chip in (">Signed<", ">Signature invalid<", ">Signature not verified<", ">Checking signature<"):
            assert chip not in html

    def test_unreadable_result_is_an_error_not_a_verdict(
        self, page: tuple[Client, Component, SBOM], mocker: MockerFixture
    ) -> None:
        _client, _component, sbom = page
        mocker.patch("sbomify.apps.plugins.result_store.get_result", side_effect=OSError("gone"))
        run = _run(sbom, result=None)
        AssessmentRun.objects.filter(pk=run.pk).update(result_object_key="missing/key.json")

        assert not get_signature_status(sbom.id).ok

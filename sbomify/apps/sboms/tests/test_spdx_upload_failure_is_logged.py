"""An SPDX upload that fails for our reasons leaves a record.

Everything the handler raises becomes one opaque ``400 Invalid request``. The
CycloneDX and VEX handlers next to it log before returning that; the SPDX one
did not, so a fault on our side was indistinguishable from a malformed document
and left nothing behind to find it by. A missing jsonschema in the SPDX 3
validator surfaced as exactly that 400, silently.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.models import SBOM

DOCUMENT = {
    "spdxVersion": "SPDX-2.3",
    "dataLicense": "CC0-1.0",
    "SPDXID": "SPDXRef-DOCUMENT",
    "name": "openssl",
    "documentNamespace": "https://example.test/openssl",
    "creationInfo": {"created": "2026-01-01T00:00:00Z", "creators": ["Tool: test"]},
    "packages": [
        {
            "SPDXID": "SPDXRef-Package",
            "name": "openssl",
            "versionInfo": "3.2.3",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
        }
    ],
}


@pytest.mark.django_db
def test_a_failure_inside_the_handler_is_logged(
    sample_access_token: AccessToken,
    sample_component: Component,
    mocker,
) -> None:
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_data_as_file")
    SBOM.objects.all().delete()

    url = reverse("api-1:sbom_upload_spdx", kwargs={"component_id": sample_component.id})

    # Stands in for any fault on our side, which is what the silent branch hid:
    # the real one was a missing jsonschema inside the SPDX 3 validator.
    with patch(
        "sbomify.apps.sboms.apis.validate_spdx_sbom",
        side_effect=ModuleNotFoundError("No module named 'jsonschema'"),
    ):
        with patch("sbomify.apps.sboms.apis.log") as logger:
            response = Client().post(
                url,
                data=json.dumps(DOCUMENT),
                content_type="application/json",
                **get_api_headers(sample_access_token),
            )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid request"
    # The message too, not just the call: a handler that logs something else
    # while still reaching .exception() would leave the same gap this closes.
    logger.exception.assert_called_once_with("Error processing SPDX BOM upload")

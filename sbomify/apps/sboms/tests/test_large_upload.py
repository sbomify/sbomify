"""A Yocto-sized SPDX 3 upload has to get through.

The endpoint advertised a 100 MB cap while Django's DATA_UPLOAD_MAX_MEMORY_SIZE
sat at 20 MB, so anything above 20 MB was refused while reading the body, before
the endpoint's own limit could run and say so. A Yocto image SBOM lands squarely
in that gap.
"""

import json
import os
import pathlib
import re

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.sboms.apis import SBOM_MAX_UPLOAD_SIZE
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.tests.fixtures import sample_access_token, sample_component  # noqa: F401
from sbomify.apps.sboms.tests.test_apis import get_api_headers

YOCTO = pathlib.Path(__file__).parent.resolve() / "test_data/yocto_core-image-minimal.spdx3.json"


def _yocto_scaled_to(target_mb: float) -> bytes:
    """The real Yocto fixture, its graph repeated with fresh ids until big enough."""
    doc = json.loads(YOCTO.read_text(encoding="utf-8"))
    doc_types = {"SpdxDocument", "software_Sbom"}
    singletons = [e for e in doc["@graph"] if isinstance(e, dict) and e.get("type") in doc_types]
    bulk = [e for e in doc["@graph"] if e not in singletons]

    def copy_n(n: int) -> list:
        text = json.dumps(bulk)
        text = re.sub(r'(urn:[A-Za-z0-9:_\-.]+?)(["/])', lambda m: f"{m.group(1)}-c{n}{m.group(2)}", text)
        text = re.sub(r'(_:[A-Za-z0-9_\-.]+?)(")', lambda m: f"{m.group(1)}c{n}{m.group(2)}", text)
        return json.loads(text)

    graph = list(singletons) + list(bulk)
    n = 1
    while len(json.dumps({**doc, "@graph": graph}).encode()) < target_mb * 1024 * 1024:
        graph.extend(copy_n(n))
        n += 1
    return json.dumps({**doc, "@graph": graph}).encode()


def test_the_endpoint_cap_is_reachable():
    """The regression that caused this: a cap Django refuses before we check it.

    A SBOM_MAX_UPLOAD_SIZE above DATA_UPLOAD_MAX_MEMORY_SIZE is not a cap, it is
    a number in a message nobody ever sees.
    """
    assert SBOM_MAX_UPLOAD_SIZE <= settings.DATA_UPLOAD_MAX_MEMORY_SIZE


def test_the_default_is_a_hundred_megabytes():
    assert settings.DATA_UPLOAD_MAX_MEMORY_SIZE == 100 * 1024 * 1024


def test_the_bom_cap_follows_the_shared_ceiling_by_default():
    """One number to set, not two that can disagree.

    With no SBOM-specific override, the BOM cap is the artifact ceiling, so
    moving DATA_UPLOAD_MAX_MEMORY_SIZE_MB moves this too.
    """
    assert SBOM_MAX_UPLOAD_SIZE == settings.ARTIFACT_MAX_UPLOAD_SIZE
    assert settings.ARTIFACT_MAX_UPLOAD_SIZE == settings.DATA_UPLOAD_MAX_MEMORY_SIZE


@pytest.mark.parametrize(
    "value,expected_mb",
    [("250", 250), ("100MB", 100), ("", 100), ("0", 100), ("-5", 100), ("  150  ", 150)],
)
def test_the_env_var_is_parsed_without_taking_the_app_down(value, expected_mb):
    """Parsed at import, so a typo would otherwise fail the boot, not the request."""
    from sbomify.settings import _megabytes_from_env

    monkey = os.environ.get("X_TEST_UPLOAD_MB")
    os.environ["X_TEST_UPLOAD_MB"] = value
    try:
        assert _megabytes_from_env("X_TEST_UPLOAD_MB", 100) == expected_mb * 1024 * 1024
    finally:
        if monkey is None:
            os.environ.pop("X_TEST_UPLOAD_MB", None)
        else:
            os.environ["X_TEST_UPLOAD_MB"] = monkey


@pytest.mark.django_db
def test_a_yocto_sized_spdx3_document_uploads(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,
):
    """25 MB, the size the pilot customer reported failing."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_data_as_file")
    SBOM.objects.all().delete()

    body = _yocto_scaled_to(25)
    assert len(body) > 20 * 1024 * 1024, "must exceed the old 20 MB ceiling to be the regression test"
    assert len(body) < SBOM_MAX_UPLOAD_SIZE

    response = Client().post(
        reverse("api-1:sbom_upload_spdx", kwargs={"component_id": sample_component.id}),
        data=body,
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201, f"{len(body) / 1024 / 1024:.1f} MB refused: {response.content[:300]}"
    assert SBOM.objects.count() == 1

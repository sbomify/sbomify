"""auth=None routes only see a bearer through optional_auth.

get_sbom and download_sbom lacked the decorator their siblings carry, so the
token that had just uploaded a private SBOM was anonymous on the way back and
got a 403. Found by the live sweep: upload 201, read-back 403, same token,
both API versions.
"""

from __future__ import annotations

import pytest
from django.test import Client

from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.models import SBOM, Component


@pytest.mark.django_db
class TestAPatCanReadBackItsOwnUpload:
    def test_detail_with_the_uploading_token(self, sample_team_with_owner_member, sample_access_token):
        component = Component.objects.create(
            team=sample_team_with_owner_member.team, name="pat-readback", component_type="bom"
        )
        sbom = SBOM.objects.create(
            component=component,
            name="pat-readback",
            format="cyclonedx",
            format_version="1.6",
            version="1.0.0",
            sbom_filename="absent.json",
            source="api",
        )

        detail = Client().get(f"/api/v1/sboms/{sbom.id}", **get_api_headers(sample_access_token))
        assert detail.status_code == 200, detail.content

        anonymous = Client().get(f"/api/v1/sboms/{sbom.id}")
        assert anonymous.status_code == 403

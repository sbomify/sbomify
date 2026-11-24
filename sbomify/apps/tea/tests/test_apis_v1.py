"""TEA 1.0.0, served at /tea/v1.0.0/ next to 0.4.0.

libtea's conformance suite (test_conformance.py) checks the shapes a 1.0.0
client parses. These tests cover what it does not: how sbomify pages, sorts,
rejects a bad request, discovers by PURL, and serves an artifact it has no
checksum for.
"""

from __future__ import annotations

import base64
from datetime import timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client, override_settings
from django.utils import timezone

from sbomify.apps.core.models import ComponentRelease, Product, Release
from sbomify.apps.sboms.models import ProductIdentifier
from sbomify.apps.tea.mappers import TEA_API_VERSION, TEA_V1_VERSION

V1 = f"/tea/v{TEA_V1_VERSION}"
V04 = f"/tea/v{TEA_API_VERSION}"
NONEXISTENT_UUID = "00000000-0000-0000-0000-000000000000"

pytestmark = pytest.mark.django_db


def get(path: str, team: Any, **params: Any) -> Any:
    response = Client().get(path, {"workspace_key": team.key, **params})
    is_json = response.headers.get("Content-Type", "").startswith("application/json")
    return response, (response.json() if is_json else None)


def nulls(value: Any, where: str = "$") -> list[str]:
    """Every path in a JSON document that holds null. TEA 1.0.0 allows none."""
    if value is None:
        return [where]
    if isinstance(value, dict):
        return [p for key, item in value.items() for p in nulls(item, f"{where}.{key}")]
    if isinstance(value, list):
        return [p for i, item in enumerate(value) for p in nulls(item, f"{where}[{i}]")]
    return []


def test_a_bad_request_gets_the_tea_error_body_and_nothing_else(tea_conformance_data):
    team = tea_conformance_data[0]

    response, body = get(f"{V1}/products", team, pageSize=101)

    assert response.status_code == 400
    assert body["error"] == "INVALID_REQUEST"
    assert set(body) == {"error", "message"}
    assert "pageSize" in body["message"]


def test_an_unknown_workspace_is_an_invalid_request():
    response = Client().get(f"{V1}/products", {"workspace_key": "no-such-workspace"})

    assert response.status_code == 400
    assert response.json()["error"] == "INVALID_REQUEST"


def test_an_unknown_object_is_object_unknown_without_a_null_message(tea_conformance_data):
    response, body = get(f"{V1}/product/{NONEXISTENT_UUID}", tea_conformance_data[0])

    assert response.status_code == 404
    assert body == {"error": "OBJECT_UNKNOWN"}


class TestPaging:
    @pytest.fixture
    def three_products(self, tea_conformance_data):
        team = tea_conformance_data[0]
        for name in ("b product", "a product"):
            Product.objects.create(name=name, team=team, is_public=True)
        return team

    def test_the_token_walks_every_result_once_and_the_last_page_has_none(self, three_products):
        team = three_products
        names, token = [], None
        for _ in range(3):
            params = {"pageSize": 1, **({"pageToken": token} if token else {})}
            _, page = get(f"{V1}/products", team, **params)
            names += [product["name"] for product in page["results"]]
            token = page.get("nextPageToken")
            assert page["hasNext"] is (token is not None)

        assert names == ["a product", "b product", "test product"]
        assert token is None

    def test_desc_reverses_the_order(self, three_products):
        _, page = get(f"{V1}/products", three_products, sortOrder="desc")

        assert [product["name"] for product in page["results"]] == ["test product", "b product", "a product"]

    def test_a_token_from_another_query_is_rejected(self, three_products):
        team = three_products
        _, first = get(f"{V1}/products", team, pageSize=1)

        response, body = get(f"{V1}/products", team, pageSize=1, pageToken=first["nextPageToken"], sortOrder="desc")

        assert response.status_code == 400
        assert body["error"] == "INVALID_PAGE_TOKEN"

    def test_a_token_from_another_path_is_rejected(self, three_products):
        team = three_products
        _, first = get(f"{V1}/products", team, pageSize=1)

        response, body = get(f"{V1}/components", team, pageToken=first["nextPageToken"])

        assert response.status_code == 400
        assert body["error"] == "INVALID_PAGE_TOKEN"

    def test_a_forged_token_is_rejected(self, three_products):
        response, body = get(f"{V1}/products", three_products, pageToken="eyJvZmZzZXQiOjF9")

        assert response.status_code == 400
        assert body["error"] == "INVALID_PAGE_TOKEN"

    def test_a_release_without_a_release_date_sorts_last_ascending_and_first_descending(self, tea_conformance_data):
        team, product, undated = tea_conformance_data[:3]
        # save() fills in a missing release date, so clear it directly.
        Release.objects.filter(pk=undated.pk).update(released_at=None)
        Release.objects.create(product=product, name="2.0.0", released_at=timezone.now() + timedelta(days=1))
        url = f"{V1}/product/{product.uuid}/releases"

        _, ascending = get(url, team, sortField="releaseDate")
        _, descending = get(url, team, sortField="releaseDate", sortOrder="desc")

        assert [r["version"] for r in ascending["results"]] == ["2.0.0", "v1.0.0-conformance"]
        assert [r["version"] for r in descending["results"]] == ["v1.0.0-conformance", "2.0.0"]

    def test_component_releases_are_paged(self, tea_conformance_data):
        team, component = tea_conformance_data[0], tea_conformance_data[3]
        ComponentRelease.objects.create(component=component, version="9.9.9")

        _, page = get(f"{V1}/component/{component.uuid}/releases", team, pageSize=1, sortField="version")

        assert page["hasNext"] is True
        assert len(page["results"]) == 1


class TestDiscovery:
    def test_both_tei_forms_find_the_release(self, tea_conformance_data):
        team, product, release = tea_conformance_data[:3]

        for tei in (f"tei://example.com/uuid/{product.uuid}", f"urn:tei:uuid:example.com:{product.uuid}"):
            response, body = get(f"{V1}/discovery", team, tei=tei)

            assert response.status_code == 200, tei
            assert body[0]["productReleaseUuid"] == str(release.uuid)
            assert body[0]["servers"][0]["versions"] == [TEA_V1_VERSION, TEA_API_VERSION]

    def test_a_purl_finds_the_release_of_its_version(self, tea_conformance_data):
        team, product = tea_conformance_data[:2]
        ProductIdentifier.objects.create(
            product=product, team=team, identifier_type=ProductIdentifier.IdentifierType.PURL, value="pkg:pypi/x"
        )
        versioned = Release.objects.create(product=product, name="3.1.0", version="3.1.0")

        _, by_purl = get(f"{V1}/discovery", team, purl="pkg:pypi/x@3.1.0")
        encoded = base64.urlsafe_b64encode(b"pkg:pypi/x@3.1.0").rstrip(b"=").decode()
        _, by_purl_tei = get(f"{V1}/discovery", team, tei=f"tei://example.com/purl/{encoded}")

        assert [entry["productReleaseUuid"] for entry in by_purl] == [str(versioned.uuid)]
        assert by_purl_tei == by_purl

    @pytest.mark.parametrize("params", [{}, {"tei": "urn:tei:uuid:example.com:x", "purl": "pkg:pypi/x"}])
    def test_exactly_one_identifier_is_required(self, tea_conformance_data, params):
        response, body = get(f"{V1}/discovery", tea_conformance_data[0], **params)

        assert response.status_code == 400
        assert body["error"] == "INVALID_REQUEST"

    def test_an_unknown_identifier_is_object_unknown(self, tea_conformance_data):
        response, body = get(f"{V1}/discovery", tea_conformance_data[0], purl="pkg:pypi/nobody")

        assert response.status_code == 404
        assert body == {"error": "OBJECT_UNKNOWN"}

    def test_0_4_0_discovery_advertises_both_versions_too(self, tea_conformance_data):
        team, product = tea_conformance_data[:2]

        _, body = get(f"{V04}/discovery", team, tei=f"urn:tei:uuid:example.com:{product.uuid}")

        assert body[0]["servers"][0]["versions"] == [TEA_V1_VERSION, TEA_API_VERSION]


class TestShapes:
    def test_a_product_release_carries_its_latest_collection(self, tea_conformance_data):
        team, release, sbom = tea_conformance_data[0], tea_conformance_data[2], tea_conformance_data[4]

        _, body = get(f"{V1}/productRelease/{release.uuid}", team)

        collection = body["latestCollection"]
        assert collection["belongsTo"] == "PRODUCT_RELEASE"
        assert "createdDate" in collection and "date" not in collection
        assert [artifact["uuid"] for artifact in collection["artifacts"]] == [str(sbom.uuid)]
        assert nulls(body) == []

    def test_a_component_release_is_flat(self, tea_conformance_data):
        team, component, sbom = tea_conformance_data[0], tea_conformance_data[3], tea_conformance_data[4]
        component_release = ComponentRelease.objects.get(component=component, version=sbom.version)

        _, body = get(f"{V1}/componentRelease/{component_release.uuid}", team)

        assert "release" not in body
        assert body["uuid"] == str(component_release.uuid)
        assert body["component"] == str(component.uuid)
        assert body["latestCollection"]["belongsTo"] == "COMPONENT_RELEASE"
        assert nulls(body) == []

    def test_only_identifier_types_1_0_0_defines_are_published(self, tea_conformance_data):
        team, product = tea_conformance_data[:2]
        for identifier_type, value in (
            (ProductIdentifier.IdentifierType.PURL, "pkg:pypi/x"),
            (ProductIdentifier.IdentifierType.GTIN_13, "4006381333931"),
        ):
            ProductIdentifier.objects.create(product=product, team=team, identifier_type=identifier_type, value=value)

        _, v1 = get(f"{V1}/product/{product.uuid}", team)
        _, v04 = get(f"{V04}/product/{product.uuid}", team)

        assert [i["idType"] for i in v1["identifiers"]] == ["PURL"]
        assert sorted(i["idType"] for i in v04["identifiers"]) == ["GTIN", "PURL"]

    def test_components_and_component_releases_are_listed(self, tea_conformance_data):
        team, component = tea_conformance_data[0], tea_conformance_data[3]

        _, components = get(f"{V1}/components", team)
        _, releases = get(f"{V1}/componentReleases", team)
        _, filtered = get(f"{V1}/componentReleases", team, idType="PURL", idValue="pkg:pypi/x")

        assert [c["uuid"] for c in components["results"]] == [str(component.uuid)]
        assert [r["component"] for r in releases["results"]] == [str(component.uuid)]
        assert filtered == {"hasNext": False, "results": []}


class TestArtifacts:
    def test_the_one_revision_is_version_1_and_also_latest(self, tea_conformance_data):
        team, sbom = tea_conformance_data[0], tea_conformance_data[4]

        _, latest = get(f"{V1}/artifact/{sbom.uuid}/latest", team)
        _, first = get(f"{V1}/artifact/{sbom.uuid}/1", team)
        response, _ = get(f"{V1}/artifact/{sbom.uuid}/2", team)

        assert latest == first
        assert latest["version"] == 1
        assert latest["createdDate"]
        assert response.status_code == 404

    def test_a_format_with_a_checksum_publishes_its_url(self, tea_conformance_data):
        team, sbom = tea_conformance_data[0], tea_conformance_data[4]
        sbom.sha256_hash = "a" * 64
        sbom.save()

        _, artifact = get(f"{V1}/artifact/{sbom.uuid}/latest", team)

        (fmt,) = artifact["formats"]
        assert fmt["url"].endswith(f"/api/v1/sboms/{sbom.uuid}/download")
        assert fmt["checksums"] == [{"algType": "SHA-256", "algValue": "a" * 64}]

    def test_a_format_without_a_checksum_is_downloaded_through_tea(self, tea_conformance_data):
        team, sbom = tea_conformance_data[0], tea_conformance_data[4]
        assert not sbom.sha256_hash

        _, artifact = get(f"{V1}/artifact/{sbom.uuid}/latest", team)
        (fmt,) = artifact["formats"]
        response, _ = get(f"{V1}/artifact/{sbom.uuid}/1/download", team, mediaType=fmt["mediaType"].upper())

        assert "url" not in fmt and "checksums" not in fmt
        assert response.status_code == 302
        assert response["Location"].endswith(f"/api/v1/sboms/{sbom.uuid}/download")

    def test_a_media_type_the_artifact_lacks_is_no_acceptable_format(self, tea_conformance_data):
        team, sbom = tea_conformance_data[0], tea_conformance_data[4]

        response, body = get(f"{V1}/artifact/{sbom.uuid}/latest/download", team, mediaType="text/plain")

        assert response.status_code == 406
        assert body == {"error": "NO_ACCEPTABLE_FORMAT"}

    def test_a_signature_redirects_or_is_signature_not_found(self, tea_conformance_data):
        team, sbom = tea_conformance_data[0], tea_conformance_data[4]

        missing, body = get(f"{V1}/artifact/{sbom.uuid}/latest/signature/download", team)
        sbom.signature_url = "https://signatures.example.com/sbom.sig"
        sbom.save()
        found, _ = get(f"{V1}/artifact/{sbom.uuid}/1/signature/download", team)

        assert (missing.status_code, body) == (404, {"error": "SIGNATURE_NOT_FOUND"})
        assert (found.status_code, found["Location"]) == (302, "https://signatures.example.com/sbom.sig")


@override_settings(TEA_CACHE_TTL=300, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
def test_the_two_versions_do_not_share_cached_responses(tea_conformance_data):
    """Both versions cache under the same object names; a shared entry would serve
    one version's shape from the other's path."""
    team, release = tea_conformance_data[0], tea_conformance_data[2]
    cache.clear()

    _, v04 = get(f"{V04}/productRelease/{release.uuid}", team)
    _, v1 = get(f"{V1}/productRelease/{release.uuid}", team)

    assert "latestCollection" not in v04
    assert "latestCollection" in v1
    cache.clear()

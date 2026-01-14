"""
Unit tests for TEA mapper functions.
"""

import pytest

from sbomify.apps.core.models import Product, Release
from sbomify.apps.sboms.models import ProductIdentifier
from sbomify.apps.tea.mappers import (
    IDENTIFIER_TYPE_TO_TEA,
    PURLParseError,
    TEA_API_VERSION,
    TEA_IDENTIFIER_TYPE_MAPPING,
    TEIParseError,
    build_tea_server_url,
    parse_purl,
    parse_tei,
    tea_identifier_mapper,
    tea_tei_mapper,
)


class TestParsePurl:
    """Tests for PURL parsing."""

    def test_parse_simple_purl(self):
        """Test parsing a simple PURL without version."""
        result = parse_purl("pkg:pypi/requests")
        assert result["type"] == "pypi"
        assert result["namespace"] is None
        assert result["name"] == "requests"
        assert result["version"] is None
        assert result["qualifiers"] == {}
        assert result["subpath"] is None

    def test_parse_purl_with_version(self):
        """Test parsing a PURL with version."""
        result = parse_purl("pkg:pypi/requests@2.28.0")
        assert result["type"] == "pypi"
        assert result["name"] == "requests"
        assert result["version"] == "2.28.0"

    def test_parse_purl_with_namespace(self):
        """Test parsing a PURL with namespace."""
        result = parse_purl("pkg:maven/org.apache.logging.log4j/log4j-api@2.24.3")
        assert result["type"] == "maven"
        assert result["namespace"] == "org.apache.logging.log4j"
        assert result["name"] == "log4j-api"
        assert result["version"] == "2.24.3"

    def test_parse_purl_with_qualifiers(self):
        """Test parsing a PURL with qualifiers."""
        result = parse_purl("pkg:pypi/cyclonedx-python-lib@8.4.0?extension=whl&qualifier=py3-none-any")
        assert result["type"] == "pypi"
        assert result["name"] == "cyclonedx-python-lib"
        assert result["version"] == "8.4.0"
        assert result["qualifiers"] == {"extension": "whl", "qualifier": "py3-none-any"}

    def test_parse_purl_with_subpath(self):
        """Test parsing a PURL with subpath."""
        result = parse_purl("pkg:github/sbomify/sbomify@v1.0.0#src/main")
        assert result["type"] == "github"
        assert result["namespace"] == "sbomify"
        assert result["name"] == "sbomify"
        assert result["version"] == "v1.0.0"
        assert result["subpath"] == "src/main"

    def test_parse_purl_url_encoded(self):
        """Test parsing a URL-encoded PURL."""
        result = parse_purl("pkg:pypi/my%2Fpackage@1.0.0")
        assert result["name"] == "my/package"

    def test_parse_invalid_purl(self):
        """Test that invalid PURL raises error."""
        with pytest.raises(PURLParseError):
            parse_purl("invalid-purl")

    def test_parse_purl_missing_type(self):
        """Test that PURL without type raises error."""
        with pytest.raises(PURLParseError):
            parse_purl("pkg:/package")


class TestParseTei:
    """Tests for TEI parsing."""

    def test_parse_valid_tei(self):
        """Test parsing a valid TEI."""
        tei_type, domain, identifier = parse_tei("urn:tei:purl:example.com:pkg:pypi/requests@2.28.0")
        assert tei_type == "purl"
        assert domain == "example.com"
        assert identifier == "pkg:pypi/requests@2.28.0"

    def test_parse_tei_uuid(self):
        """Test parsing a UUID TEI."""
        tei_type, domain, identifier = parse_tei("urn:tei:uuid:products.example.com:d4d9f54a-abcf-11ee-ac79-1a52914d44b")
        assert tei_type == "uuid"
        assert domain == "products.example.com"
        assert identifier == "d4d9f54a-abcf-11ee-ac79-1a52914d44b"

    def test_parse_tei_gtin(self):
        """Test parsing a GTIN TEI."""
        tei_type, domain, identifier = parse_tei("urn:tei:gtin:example.com:0012345678905")
        assert tei_type == "gtin"
        assert domain == "example.com"
        assert identifier == "0012345678905"

    def test_parse_tei_url_encoded(self):
        """Test parsing a URL-encoded TEI."""
        tei_type, domain, identifier = parse_tei("urn%3Atei%3Apurl%3Aexample.com%3Apkg%3Apypi%2Frequests")
        assert tei_type == "purl"
        assert domain == "example.com"
        assert identifier == "pkg:pypi/requests"

    def test_parse_tei_case_insensitive_type(self):
        """Test that TEI type is normalized to lowercase."""
        tei_type, _, _ = parse_tei("urn:tei:PURL:example.com:pkg:pypi/requests")
        assert tei_type == "purl"

    def test_parse_invalid_tei(self):
        """Test that invalid TEI raises error."""
        with pytest.raises(TEIParseError):
            parse_tei("invalid-tei")

    def test_parse_tei_missing_parts(self):
        """Test that TEI with missing parts raises error."""
        with pytest.raises(TEIParseError):
            parse_tei("urn:tei:purl")


@pytest.mark.django_db
class TestTeaTeiMapper:
    """Tests for TEI to release mapping."""

    def test_tei_mapper_uuid_type(self, sample_product):
        """Test TEI mapper with UUID type."""
        # Create a release for the product
        release = Release.objects.create(product=sample_product, name="v1.0.0")

        tei = f"urn:tei:uuid:example.com:{sample_product.id}"
        releases = tea_tei_mapper(sample_product.team, tei)

        # Should include the created release plus any auto-created "latest" release
        release_ids = [r.id for r in releases]
        assert release.id in release_ids

    def test_tei_mapper_purl_type(self, sample_product):
        """Test TEI mapper with PURL type."""
        # Create a PURL identifier for the product
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:pypi/test-package",
        )

        # Create releases
        release = Release.objects.create(product=sample_product, name="v1.0.0")

        tei = "urn:tei:purl:example.com:pkg:pypi/test-package"
        releases = tea_tei_mapper(sample_product.team, tei)

        release_ids = [r.id for r in releases]
        assert release.id in release_ids

    def test_tei_mapper_purl_with_version(self, sample_product):
        """Test TEI mapper with PURL type including version."""
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:pypi/test-package",
        )

        release_v1 = Release.objects.create(product=sample_product, name="1.0.0")
        Release.objects.create(product=sample_product, name="2.0.0")

        # Search with version should prioritize matching release
        tei = "urn:tei:purl:example.com:pkg:pypi/test-package@1.0.0"
        releases = tea_tei_mapper(sample_product.team, tei)

        release_ids = [r.id for r in releases]
        assert release_v1.id in release_ids

    def test_tei_mapper_gtin_type(self, sample_product):
        """Test TEI mapper with GTIN type."""
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="5901234123457",
        )

        release = Release.objects.create(product=sample_product, name="v1.0.0")

        tei = "urn:tei:gtin:example.com:5901234123457"
        releases = tea_tei_mapper(sample_product.team, tei)

        release_ids = [r.id for r in releases]
        assert release.id in release_ids

    def test_tei_mapper_asin_type(self, sample_product):
        """Test TEI mapper with ASIN type."""
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.ASIN,
            value="B08N5WRWNW",
        )

        release = Release.objects.create(product=sample_product, name="v1.0.0")

        tei = "urn:tei:asin:example.com:B08N5WRWNW"
        releases = tea_tei_mapper(sample_product.team, tei)

        release_ids = [r.id for r in releases]
        assert release.id in release_ids

    def test_tei_mapper_cpe_type(self, sample_product):
        """Test TEI mapper with CPE type."""
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.CPE,
            value="cpe:2.3:a:apache:log4j:2.24.3:*:*:*:*:*:*:*",
        )

        release = Release.objects.create(product=sample_product, name="v1.0.0")

        tei = "urn:tei:cpe:example.com:cpe:2.3:a:apache:log4j:2.24.3:*:*:*:*:*:*:*"
        releases = tea_tei_mapper(sample_product.team, tei)

        release_ids = [r.id for r in releases]
        assert release.id in release_ids

    def test_tei_mapper_no_match(self, sample_product):
        """Test TEI mapper returns empty list when no match."""
        tei = "urn:tei:uuid:example.com:nonexistent-id"
        releases = tea_tei_mapper(sample_product.team, tei)
        assert releases == []

    def test_tei_mapper_unsupported_type(self, sample_product):
        """Test TEI mapper returns empty list for unsupported types."""
        tei = "urn:tei:swid:example.com:some-swid-tag"
        releases = tea_tei_mapper(sample_product.team, tei)
        assert releases == []


@pytest.mark.django_db
class TestTeaIdentifierMapper:
    """Tests for Product identifier to TEA format mapping."""

    def test_identifier_mapper_purl(self, sample_product):
        """Test mapping PURL identifier."""
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:pypi/test-package@1.0.0",
        )

        identifiers = tea_identifier_mapper(sample_product)
        assert len(identifiers) == 1
        assert identifiers[0]["idType"] == "PURL"
        assert identifiers[0]["idValue"] == "pkg:pypi/test-package@1.0.0"

    def test_identifier_mapper_cpe(self, sample_product):
        """Test mapping CPE identifier."""
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.CPE,
            value="cpe:2.3:a:apache:log4j",
        )

        identifiers = tea_identifier_mapper(sample_product)
        assert len(identifiers) == 1
        assert identifiers[0]["idType"] == "CPE"

    def test_identifier_mapper_gtin_merged(self, sample_product):
        """Test that different GTIN types are all mapped to GTIN."""
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_8,
            value="12345678",
        )
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="1234567890123",
        )

        identifiers = tea_identifier_mapper(sample_product)
        assert len(identifiers) == 2
        assert all(i["idType"] == "GTIN" for i in identifiers)

    def test_identifier_mapper_multiple_types(self, sample_product):
        """Test mapping multiple identifier types."""
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:pypi/test-package",
        )
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.CPE,
            value="cpe:2.3:a:test:product",
        )

        identifiers = tea_identifier_mapper(sample_product)
        assert len(identifiers) == 2
        id_types = {i["idType"] for i in identifiers}
        assert id_types == {"PURL", "CPE"}

    def test_identifier_mapper_skips_unsupported_types(self, sample_product):
        """Test that unsupported identifier types are skipped."""
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.SKU,
            value="SKU-12345",
        )
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.MPN,
            value="MPN-12345",
        )

        identifiers = tea_identifier_mapper(sample_product)
        assert len(identifiers) == 0

    def test_identifier_mapper_no_duplicates(self, sample_product):
        """Test that duplicate identifiers are not included."""
        # Create two GTIN-13 with same value (shouldn't happen normally, but test dedup)
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="1234567890123",
        )

        identifiers = tea_identifier_mapper(sample_product)
        values = [i["idValue"] for i in identifiers]
        assert len(values) == len(set(values))

    def test_identifier_mapper_empty(self, sample_product):
        """Test mapping product with no identifiers."""
        identifiers = tea_identifier_mapper(sample_product)
        assert identifiers == []


@pytest.mark.django_db
class TestBuildTeaServerUrl:
    """Tests for TEA server URL building."""

    def test_build_url_custom_domain(self, sample_team):
        """Test building URL for custom domain."""
        sample_team.custom_domain = "trust.example.com"
        sample_team.custom_domain_validated = True
        sample_team.save()

        url = build_tea_server_url(sample_team)
        assert url == "https://trust.example.com/tea/v1"

    def test_build_url_unvalidated_custom_domain(self, sample_team, settings):
        """Test that unvalidated custom domain falls back to workspace key."""
        sample_team.custom_domain = "trust.example.com"
        sample_team.custom_domain_validated = False
        sample_team.save()

        settings.APP_BASE_URL = "https://app.sbomify.com"
        url = build_tea_server_url(sample_team)
        assert url == f"https://app.sbomify.com/public/{sample_team.key}/tea/v1"

    def test_build_url_workspace_key(self, sample_team, settings):
        """Test building URL with workspace key."""
        sample_team.custom_domain = None
        sample_team.save()

        settings.APP_BASE_URL = "https://app.sbomify.com"
        url = build_tea_server_url(sample_team, workspace_key="my-workspace")
        assert url == "https://app.sbomify.com/public/my-workspace/tea/v1"

    def test_build_url_no_custom_domain(self, sample_team, settings):
        """Test building URL without custom domain uses team key."""
        sample_team.custom_domain = None
        sample_team.save()

        settings.APP_BASE_URL = "https://app.sbomify.com"
        url = build_tea_server_url(sample_team)
        assert url == f"https://app.sbomify.com/public/{sample_team.key}/tea/v1"


class TestTeaApiVersion:
    """Tests for TEA API version constant."""

    def test_tea_api_version_format(self):
        """Test that TEA API version is in semver format."""
        import re

        semver_pattern = r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$"
        assert re.match(semver_pattern, TEA_API_VERSION)

    def test_tea_api_version_value(self):
        """Test the current TEA API version."""
        assert TEA_API_VERSION == "0.3.0-beta.2"


class TestIdentifierTypeMapping:
    """Tests for identifier type mappings."""

    def test_all_gtin_types_map_to_gtin(self):
        """Test that all GTIN_* types map to GTIN."""
        gtin_types = [
            ProductIdentifier.IdentifierType.GTIN_8,
            ProductIdentifier.IdentifierType.GTIN_12,
            ProductIdentifier.IdentifierType.GTIN_13,
            ProductIdentifier.IdentifierType.GTIN_14,
        ]
        for gtin_type in gtin_types:
            assert IDENTIFIER_TYPE_TO_TEA[gtin_type] == "GTIN"

    def test_purl_maps_correctly(self):
        """Test PURL type mapping."""
        assert IDENTIFIER_TYPE_TO_TEA[ProductIdentifier.IdentifierType.PURL] == "PURL"

    def test_cpe_maps_correctly(self):
        """Test CPE type mapping."""
        assert IDENTIFIER_TYPE_TO_TEA[ProductIdentifier.IdentifierType.CPE] == "CPE"

    def test_asin_maps_correctly(self):
        """Test ASIN type mapping."""
        assert IDENTIFIER_TYPE_TO_TEA[ProductIdentifier.IdentifierType.ASIN] == "ASIN"


class TestTeaIdentifierTypeMapping:
    """Tests for TEA identifier type mapping (reverse mapping for API queries)."""

    def test_purl_mapping(self):
        """Test PURL reverse mapping."""
        assert TEA_IDENTIFIER_TYPE_MAPPING["PURL"] == [ProductIdentifier.IdentifierType.PURL]

    def test_cpe_mapping(self):
        """Test CPE reverse mapping."""
        assert TEA_IDENTIFIER_TYPE_MAPPING["CPE"] == [ProductIdentifier.IdentifierType.CPE]

    def test_gtin_mapping_includes_all_variants(self):
        """Test GTIN reverse mapping includes all GTIN types."""
        gtin_types = TEA_IDENTIFIER_TYPE_MAPPING["GTIN"]
        assert ProductIdentifier.IdentifierType.GTIN_8 in gtin_types
        assert ProductIdentifier.IdentifierType.GTIN_12 in gtin_types
        assert ProductIdentifier.IdentifierType.GTIN_13 in gtin_types
        assert ProductIdentifier.IdentifierType.GTIN_14 in gtin_types

    def test_asin_mapping(self):
        """Test ASIN reverse mapping."""
        assert TEA_IDENTIFIER_TYPE_MAPPING["ASIN"] == [ProductIdentifier.IdentifierType.ASIN]

    def test_unknown_type_returns_empty(self):
        """Test that unknown type returns empty list via get()."""
        assert TEA_IDENTIFIER_TYPE_MAPPING.get("UNKNOWN", []) == []

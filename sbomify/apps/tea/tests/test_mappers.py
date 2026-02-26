"""
Unit tests for TEA mapper functions.
"""

import pytest
from pydantic import ValidationError as PydanticValidationError

from sbomify.apps.core.models import Release
from sbomify.apps.core.purl import PURLParseError, parse_purl, strip_purl_version
from sbomify.apps.core.schemas import (
    ComponentIdentifierCreateSchema,
    ProductIdentifierCreateSchema,
)
from sbomify.apps.sboms.models import ComponentIdentifier, ProductIdentifier
from sbomify.apps.tea.mappers import (
    IDENTIFIER_TYPE_TO_TEA,
    TEA_API_VERSION,
    TEA_IDENTIFIER_TYPE_MAPPING,
    TEIParseError,
    build_product_tei_urn,
    build_tea_server_url,
    get_product_tei_urn,
    parse_tei,
    tea_component_identifier_mapper,
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


class TestStripPurlVersion:
    """Tests for PURL version stripping."""

    def test_strip_version_simple(self):
        result = strip_purl_version("pkg:pypi/requests@2.28.0")
        assert result == "pkg:pypi/requests"

    def test_strip_version_with_namespace(self):
        result = strip_purl_version("pkg:npm/@scope/package@1.0.0")
        assert result == "pkg:npm/@scope/package"

    def test_strip_version_preserves_qualifiers(self):
        result = strip_purl_version("pkg:pypi/requests@2.28.0?extension=whl")
        assert result == "pkg:pypi/requests?extension=whl"

    def test_strip_version_preserves_subpath(self):
        result = strip_purl_version("pkg:github/sbomify/sbomify@v1.0.0#src/main")
        assert result == "pkg:github/sbomify/sbomify#src/main"

    def test_strip_version_preserves_qualifiers_and_subpath(self):
        result = strip_purl_version("pkg:pypi/lib@1.0?ext=whl#src")
        assert result == "pkg:pypi/lib?ext=whl#src"

    def test_no_version_unchanged(self):
        result = strip_purl_version("pkg:pypi/requests")
        assert result == "pkg:pypi/requests"

    def test_no_version_with_qualifiers_unchanged(self):
        result = strip_purl_version("pkg:pypi/requests?extension=whl")
        assert result == "pkg:pypi/requests?extension=whl"

    def test_invalid_purl_raises(self):
        with pytest.raises(PURLParseError):
            strip_purl_version("not-a-purl")

    def test_invalid_purl_missing_pkg(self):
        with pytest.raises(PURLParseError):
            strip_purl_version("npm/package@1.0.0")


class TestPurlSchemaValidation:
    """Tests for PURL validation in identifier schemas."""

    def test_create_schema_strips_version(self):
        schema = ProductIdentifierCreateSchema(identifier_type="purl", value="pkg:pypi/requests@2.28.0")
        assert schema.value == "pkg:pypi/requests"

    def test_create_schema_strips_version_scoped(self):
        schema = ProductIdentifierCreateSchema(identifier_type="purl", value="pkg:npm/@scope/package@1.0.0")
        assert schema.value == "pkg:npm/@scope/package"

    def test_create_schema_invalid_purl_raises(self):
        with pytest.raises(PydanticValidationError):
            ProductIdentifierCreateSchema(identifier_type="purl", value="not-a-purl")

    def test_create_schema_non_purl_unchanged(self):
        schema = ProductIdentifierCreateSchema(identifier_type="cpe", value="cpe:2.3:a:vendor:product")
        assert schema.value == "cpe:2.3:a:vendor:product"

    def test_component_schema_strips_version(self):
        schema = ComponentIdentifierCreateSchema(identifier_type="purl", value="pkg:pypi/lib@3.0")
        assert schema.value == "pkg:pypi/lib"

    def test_component_schema_invalid_purl_raises(self):
        with pytest.raises(PydanticValidationError):
            ComponentIdentifierCreateSchema(identifier_type="purl", value="invalid")

    def test_schema_preserves_url_encoding(self):
        schema = ProductIdentifierCreateSchema(identifier_type="purl", value="pkg:pypi/my%2Fpackage@1.0.0")
        assert schema.value == "pkg:pypi/my%2Fpackage"


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
        tei = "urn:tei:uuid:products.example.com:d4d9f54a-abcf-11ee-ac79-1a52914d44b"
        tei_type, domain, identifier = parse_tei(tei)
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

    def test_parse_tei_short_string_rejected(self):
        """Test that very short strings are rejected without regex."""
        with pytest.raises(TEIParseError):
            parse_tei("urn:tei:")

    def test_parse_tei_empty_string(self):
        """Test that empty string raises error."""
        with pytest.raises(TEIParseError):
            parse_tei("")


@pytest.mark.django_db
class TestTeaTeiMapper:
    """Tests for TEI to release mapping."""

    def test_tei_mapper_uuid_type(self, tea_enabled_product):
        """Test TEI mapper with UUID type."""
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        tei = f"urn:tei:uuid:example.com:{tea_enabled_product.id}"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)

        release_ids = [r.id for r in releases]
        assert release.id in release_ids

    def test_tei_mapper_purl_type(self, tea_enabled_product):
        """Test TEI mapper with PURL type."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:pypi/test-package",
        )

        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        tei = "urn:tei:purl:example.com:pkg:pypi/test-package"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)

        release_ids = [r.id for r in releases]
        assert release.id in release_ids

    def test_tei_mapper_purl_with_version(self, tea_enabled_product):
        """Test TEI mapper with PURL type including version."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:pypi/test-package",
        )

        release_v1 = Release.objects.create(product=tea_enabled_product, name="January Release", version="1.0.0")
        Release.objects.create(product=tea_enabled_product, name="February Release", version="2.0.0")

        tei = "urn:tei:purl:example.com:pkg:pypi/test-package@1.0.0"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)

        assert len(releases) == 1
        assert releases[0].id == release_v1.id

    def test_tei_mapper_purl_with_version_name_fallback(self, tea_enabled_product):
        """Test TEI mapper falls back to Release.name when version field is empty."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:pypi/test-package",
        )

        release_v1 = Release.objects.create(product=tea_enabled_product, name="1.0.0")
        Release.objects.create(product=tea_enabled_product, name="2.0.0")

        tei = "urn:tei:purl:example.com:pkg:pypi/test-package@1.0.0"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)

        assert len(releases) == 1
        assert releases[0].id == release_v1.id

    def test_tei_mapper_purl_with_version_prefers_version_field(self, tea_enabled_product):
        """Version field takes priority over name field when both could match."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:pypi/test-package",
        )

        Release.objects.create(product=tea_enabled_product, name="1.0.0")
        new_style = Release.objects.create(product=tea_enabled_product, name="January Release", version="1.0.0")

        tei = "urn:tei:purl:example.com:pkg:pypi/test-package@1.0.0"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)

        assert len(releases) == 1
        assert releases[0].id == new_style.id

    def test_tei_mapper_gtin_type(self, tea_enabled_product):
        """Test TEI mapper with GTIN type."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="5901234123457",
        )

        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        tei = "urn:tei:gtin:example.com:5901234123457"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)

        release_ids = [r.id for r in releases]
        assert release.id in release_ids

    def test_tei_mapper_asin_type(self, tea_enabled_product):
        """Test TEI mapper with ASIN type."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.ASIN,
            value="B08N5WRWNW",
        )

        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        tei = "urn:tei:asin:example.com:B08N5WRWNW"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)

        release_ids = [r.id for r in releases]
        assert release.id in release_ids

    def test_tei_mapper_cpe_type(self, tea_enabled_product):
        """Test TEI mapper with CPE type."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.CPE,
            value="cpe:2.3:a:apache:log4j:2.24.3:*:*:*:*:*:*:*",
        )

        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        tei = "urn:tei:cpe:example.com:cpe:2.3:a:apache:log4j:2.24.3:*:*:*:*:*:*:*"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)

        release_ids = [r.id for r in releases]
        assert release.id in release_ids

    def test_tei_mapper_no_match(self, sample_product):
        """Test TEI mapper returns empty list when no match."""
        tei = "urn:tei:uuid:example.com:nonexistent-id"
        releases = tea_tei_mapper(sample_product.team, tei)
        assert releases == []

    def test_tei_mapper_unsupported_type(self, sample_product):
        """Test TEI mapper raises TEIParseError for unsupported types."""
        tei = "urn:tei:swid:example.com:some-swid-tag"
        with pytest.raises(TEIParseError, match="Unsupported TEI type"):
            tea_tei_mapper(sample_product.team, tei)


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
        assert identifiers[0].idType == "PURL"
        assert identifiers[0].idValue == "pkg:pypi/test-package@1.0.0"

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
        assert identifiers[0].idType == "CPE"

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
        assert all(i.idType == "GTIN" for i in identifiers)

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
        id_types = {i.idType for i in identifiers}
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
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="1234567890123",
        )

        identifiers = tea_identifier_mapper(sample_product)
        values = [i.idValue for i in identifiers]
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
        assert url == "https://trust.example.com/tea"

    def test_build_url_unvalidated_custom_domain(self, sample_team, settings):
        """Test that unvalidated custom domain falls back to workspace key."""
        sample_team.custom_domain = "trust.example.com"
        sample_team.custom_domain_validated = False
        sample_team.save()

        settings.APP_BASE_URL = "https://app.sbomify.com"
        url = build_tea_server_url(sample_team)
        assert url == f"https://app.sbomify.com/public/{sample_team.key}/tea"

    def test_build_url_workspace_key(self, sample_team, settings):
        """Test building URL with workspace key."""
        sample_team.custom_domain = None
        sample_team.save()

        settings.APP_BASE_URL = "https://app.sbomify.com"
        url = build_tea_server_url(sample_team, workspace_key="my-workspace")
        assert url == "https://app.sbomify.com/public/my-workspace/tea"

    def test_build_url_no_custom_domain(self, sample_team, settings):
        """Test building URL without custom domain uses team key."""
        sample_team.custom_domain = None
        sample_team.save()

        settings.APP_BASE_URL = "https://app.sbomify.com"
        url = build_tea_server_url(sample_team)
        assert url == f"https://app.sbomify.com/public/{sample_team.key}/tea"

    def test_build_url_custom_domain_with_request_on_custom_domain(self, sample_team):
        """Test that request-derived URL is used when request is on the custom domain."""
        from django.test import RequestFactory

        sample_team.custom_domain = "trust.example.com"
        sample_team.custom_domain_validated = True
        sample_team.save()

        factory = RequestFactory()
        request = factory.get("/tea", HTTP_HOST="trust.example.com", HTTP_X_FORWARDED_PROTO="https")
        request.is_custom_domain = True

        url = build_tea_server_url(sample_team, request=request)
        assert url == "https://trust.example.com/tea"

    def test_build_url_custom_domain_with_request_on_main_host(self, sample_team):
        """Test that custom domain URL is used when request is NOT on the custom domain."""
        from django.test import RequestFactory

        sample_team.custom_domain = "trust.example.com"
        sample_team.custom_domain_validated = True
        sample_team.save()

        factory = RequestFactory()
        request = factory.get("/tea", HTTP_HOST="app.sbomify.com")
        request.is_custom_domain = False

        url = build_tea_server_url(sample_team, request=request)
        assert url == "https://trust.example.com/tea"


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


@pytest.mark.django_db
class TestTeaComponentIdentifierMapper:
    """Tests for Component identifier to TEA format mapping."""

    def test_component_identifier_mapper_purl(self, sample_component):
        """Test mapping component PURL identifier."""
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:npm/@example/component-package",
        )

        identifiers = tea_component_identifier_mapper(sample_component)
        assert len(identifiers) == 1
        assert identifiers[0].idType == "PURL"
        assert identifiers[0].idValue == "pkg:npm/@example/component-package"

    def test_component_identifier_mapper_cpe(self, sample_component):
        """Test mapping component CPE identifier."""
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type=ProductIdentifier.IdentifierType.CPE,
            value="cpe:2.3:a:example:component:1.0:*:*:*:*:*:*:*",
        )

        identifiers = tea_component_identifier_mapper(sample_component)
        assert len(identifiers) == 1
        assert identifiers[0].idType == "CPE"

    def test_component_identifier_mapper_gtin_merged(self, sample_component):
        """Test that different GTIN types are all mapped to GTIN for components."""
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_8,
            value="12345678",
        )
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="1234567890123",
        )

        identifiers = tea_component_identifier_mapper(sample_component)
        assert len(identifiers) == 2
        assert all(i.idType == "GTIN" for i in identifiers)

    def test_component_identifier_mapper_multiple_types(self, sample_component):
        """Test mapping multiple component identifier types."""
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:npm/@example/component",
        )
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type=ProductIdentifier.IdentifierType.CPE,
            value="cpe:2.3:a:example:component:*:*:*:*:*:*:*:*",
        )
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type=ProductIdentifier.IdentifierType.ASIN,
            value="B08N5WRWNW",
        )

        identifiers = tea_component_identifier_mapper(sample_component)
        assert len(identifiers) == 3
        id_types = {i.idType for i in identifiers}
        assert id_types == {"PURL", "CPE", "ASIN"}

    def test_component_identifier_mapper_skips_unsupported_types(self, sample_component):
        """Test that unsupported identifier types are skipped for components."""
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type=ProductIdentifier.IdentifierType.SKU,
            value="SKU-COMPONENT-12345",
        )
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type=ProductIdentifier.IdentifierType.MPN,
            value="MPN-COMPONENT-12345",
        )

        identifiers = tea_component_identifier_mapper(sample_component)
        assert len(identifiers) == 0

    def test_component_identifier_mapper_no_duplicates(self, sample_component):
        """Test that duplicate component identifiers are not included."""
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="1234567890123",
        )

        identifiers = tea_component_identifier_mapper(sample_component)
        values = [i.idValue for i in identifiers]
        assert len(values) == len(set(values))

    def test_component_identifier_mapper_empty(self, sample_component):
        """Test mapping component with no identifiers."""
        identifiers = tea_component_identifier_mapper(sample_component)
        assert identifiers == []

    def test_component_identifier_mapper_asin(self, sample_component):
        """Test mapping component ASIN identifier."""
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type=ProductIdentifier.IdentifierType.ASIN,
            value="B08N5WRWNW",
        )

        identifiers = tea_component_identifier_mapper(sample_component)
        assert len(identifiers) == 1
        assert identifiers[0].idType == "ASIN"
        assert identifiers[0].idValue == "B08N5WRWNW"


@pytest.mark.django_db
class TestTeaTeiMapperHash:
    """Tests for hash TEI type resolution."""

    def test_hash_tei_finds_sbom(self, tea_enabled_product, tea_enabled_component):
        """Test that hash TEI resolves via SBOM sha256_hash."""
        from sbomify.apps.core.models import Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM

        sbom = SBOM.objects.create(
            component=tea_enabled_component,
            name="Test SBOM",
            format="cyclonedx",
            format_version="1.4",
            source="test",
            sha256_hash="aabbccdd" * 8,
        )
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        tei = f"urn:tei:hash:example.com:SHA256:{'aabbccdd' * 8}"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)

        # May include both manual release and auto-created "latest" release (from post_save signal)
        assert len(releases) >= 1
        assert release.id in [r.id for r in releases]

    def test_hash_tei_finds_document(self, tea_enabled_product, tea_enabled_component):
        """Test that hash TEI resolves via Document sha256_hash."""
        from sbomify.apps.core.models import Release, ReleaseArtifact
        from sbomify.apps.documents.models import Document

        doc = Document.objects.create(
            name="Test Doc",
            component=tea_enabled_component,
            document_type=Document.DocumentType.LICENSE,
            content_type="text/plain",
            source="test",
            sha256_hash="11223344" * 8,
        )
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")
        ReleaseArtifact.objects.create(release=release, document=doc)

        tei = f"urn:tei:hash:example.com:SHA-256:{'11223344' * 8}"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)

        # May include auto-created "latest" release alongside the manual release
        assert len(releases) >= 1
        assert release.id in [r.id for r in releases]

    def test_hash_tei_matches_document_content_hash(self, tea_enabled_product, tea_enabled_component):
        """Hash TEI should match documents via content_hash field (not just sha256_hash)."""
        from sbomify.apps.core.models import Release, ReleaseArtifact
        from sbomify.apps.documents.models import Document

        release = Release.objects.create(product=tea_enabled_product, name="v1.0")
        doc = Document.objects.create(
            component=tea_enabled_component,
            name="test-doc",
            document_type=Document.DocumentType.OTHER,
            content_hash="abcd1234" * 8,
            source="test",
        )
        ReleaseArtifact.objects.create(release=release, document=doc)

        tei = f"urn:tei:hash:example.com:SHA256:{'abcd1234' * 8}"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)
        # May include auto-created "latest" release alongside the manual release
        assert len(releases) >= 1
        assert release.id in [r.id for r in releases]

    def test_hash_tei_excludes_private_component(self, tea_enabled_product):
        """Hash TEI should not return releases for private component artifacts."""
        from sbomify.apps.core.models import Component, Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM

        # Create a private component
        private_component = Component.objects.create(
            name="private-comp",
            team=tea_enabled_product.team,
            visibility=Component.Visibility.PRIVATE,
        )
        release = Release.objects.create(product=tea_enabled_product, name="v1.0")
        sbom = SBOM.objects.create(
            component=private_component,
            name="private-sbom",
            format="cyclonedx",
            format_version="1.4",
            source="test",
            sha256_hash="deadbeef" * 8,
        )
        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        tei = f"urn:tei:hash:example.com:SHA256:{'deadbeef' * 8}"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)
        assert len(releases) == 0

    def test_hash_tei_rejects_invalid_hex(self, tea_enabled_product):
        """Hash TEI with non-hex or wrong-length hash should raise TEIParseError."""
        team = tea_enabled_product.team

        # Too short
        with pytest.raises(TEIParseError, match="64 hexadecimal"):
            tea_tei_mapper(team, "urn:tei:hash:example.com:SHA256:abc123")

        # Non-hex characters
        with pytest.raises(TEIParseError, match="64 hexadecimal"):
            tea_tei_mapper(team, f"urn:tei:hash:example.com:SHA256:{'zzzzzzzz' * 8}")

    def test_hash_tei_rejects_unsupported_algorithm(self, tea_enabled_product):
        """Test that unsupported hash algorithm raises TEIParseError."""
        tei = "urn:tei:hash:example.com:MD5:d41d8cd98f00b204e9800998ecf8427e"
        with pytest.raises(TEIParseError, match="Unsupported hash algorithm"):
            tea_tei_mapper(tea_enabled_product.team, tei)

    def test_hash_tei_rejects_malformed(self, tea_enabled_product):
        """Test that malformed hash identifier raises TEIParseError."""
        tei = "urn:tei:hash:example.com:nocolonhere"
        with pytest.raises(TEIParseError, match="Invalid hash TEI format"):
            tea_tei_mapper(tea_enabled_product.team, tei)

    def test_hash_tei_returns_empty_for_unknown(self, tea_enabled_product):
        """Test that unknown hash returns empty list."""
        tei = f"urn:tei:hash:example.com:SHA256:{'00' * 32}"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)
        assert releases == []


@pytest.mark.django_db
class TestTeaTeiMapperEanupc:
    """Tests for eanupc TEI type resolution."""

    def test_eanupc_resolves_gtin13(self, tea_enabled_product):
        """Test that eanupc TEI resolves GTIN-13 identifiers."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="5901234123457",
        )
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        tei = "urn:tei:eanupc:example.com:5901234123457"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)

        assert len(releases) == 1
        assert release.id in [r.id for r in releases]

    def test_eanupc_resolves_gtin12(self, tea_enabled_product):
        """Test that eanupc TEI resolves GTIN-12 (UPC-A) identifiers."""
        ProductIdentifier.objects.create(
            product=tea_enabled_product,
            team=tea_enabled_product.team,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_12,
            value="012345678905",
        )
        release = Release.objects.create(product=tea_enabled_product, name="v1.0.0")

        tei = "urn:tei:eanupc:example.com:012345678905"
        releases = tea_tei_mapper(tea_enabled_product.team, tei)

        assert len(releases) == 1
        assert release.id in [r.id for r in releases]


@pytest.mark.django_db
class TestBuildProductTeiUrn:
    """Tests for build_product_tei_urn helper."""

    def test_returns_tei_when_enabled_and_validated(self, sample_team):
        """Returns correct TEI URN when tea_enabled and custom domain is validated."""
        sample_team.tea_enabled = True
        sample_team.custom_domain = "trust.example.com"
        sample_team.custom_domain_validated = True
        sample_team.save()

        result = build_product_tei_urn("some-product-id", sample_team)
        assert result == "urn:tei:uuid:trust.example.com:some-product-id"

    def test_returns_none_when_tea_disabled(self, sample_team):
        """Returns None when tea_enabled is False."""
        sample_team.tea_enabled = False
        sample_team.custom_domain = "trust.example.com"
        sample_team.custom_domain_validated = True
        sample_team.save()

        result = build_product_tei_urn("some-product-id", sample_team)
        assert result is None

    def test_returns_none_when_domain_not_validated(self, sample_team):
        """Returns None when custom domain is not validated."""
        sample_team.tea_enabled = True
        sample_team.custom_domain = "trust.example.com"
        sample_team.custom_domain_validated = False
        sample_team.save()

        result = build_product_tei_urn("some-product-id", sample_team)
        assert result is None

    def test_returns_none_when_no_custom_domain(self, sample_team):
        """Returns None when custom domain is not set."""
        sample_team.tea_enabled = True
        sample_team.custom_domain = None
        sample_team.custom_domain_validated = False
        sample_team.save()

        result = build_product_tei_urn("some-product-id", sample_team)
        assert result is None


@pytest.mark.django_db
class TestGetProductTeiUrn:
    """Tests for get_product_tei_urn service function."""

    def test_returns_tei_when_team_exists_and_configured(self, sample_team):
        """Returns TEI URN when team is found and TEA is configured."""
        sample_team.tea_enabled = True
        sample_team.custom_domain = "trust.example.com"
        sample_team.custom_domain_validated = True
        sample_team.save()

        result = get_product_tei_urn("some-product-id", sample_team.pk)
        assert result == "urn:tei:uuid:trust.example.com:some-product-id"

    def test_returns_none_when_team_not_found(self):
        """Returns None when team ID does not exist."""
        result = get_product_tei_urn("some-product-id", 999999)
        assert result is None

    def test_returns_none_when_tea_not_configured(self, sample_team):
        """Returns None when team exists but TEA is not configured."""
        sample_team.tea_enabled = False
        sample_team.save()

        result = get_product_tei_urn("some-product-id", sample_team.pk)
        assert result is None

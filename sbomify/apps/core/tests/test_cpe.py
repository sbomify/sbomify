"""CPE validation, both bindings.

Real strings throughout: a CPE that only exists in a test is no evidence the
pattern matches what NVD actually publishes.
"""

from __future__ import annotations

import pytest

from sbomify.apps.core.cpe import CPEValidationError, is_valid_cpe, validate_cpe

LOG4J_23 = "cpe:2.3:a:apache:log4j:2.14.1:*:*:*:*:*:*:*"
LOG4J_22 = "cpe:/a:apache:log4j:2.14.1"


class TestWellFormed:
    @pytest.mark.parametrize(
        "value",
        [
            LOG4J_23,
            LOG4J_22,
            "cpe:2.3:o:microsoft:windows_10:1607:*:*:*:*:*:x64:*",
            "cpe:2.3:h:cisco:asa_5500:-:*:*:*:*:*:*:*",
            # An escaped colon belongs to the field, so this is still 13 fields.
            r"cpe:2.3:a:vendor:product\:name:1.0:*:*:*:*:*:*:*",
            "cpe:/a:apache:log4j",
            "cpe:/a",
        ],
    )
    def test_accepted(self, value):
        assert is_valid_cpe(value) is True

    def test_validate_returns_the_trimmed_value(self):
        assert validate_cpe(f"  {LOG4J_23}  ") == LOG4J_23


class TestMalformed:
    @pytest.mark.parametrize(
        ("value", "why"),
        [
            ("", "empty"),
            ("   ", "whitespace"),
            ("apache:log4j:2.14.1", "no cpe prefix"),
            ("cpe:2.3:a:apache:log4j", "too few fields for 2.3"),
            ("cpe:2.3:a:apache:log4j:2.14.1:*:*:*:*:*:*:*:*", "too many fields for 2.3"),
            ("cpe:2.3:x:apache:log4j:2.14.1:*:*:*:*:*:*:*", "part must be a, o or h"),
            ("cpe:2.3:*:apache:log4j:2.14.1:*:*:*:*:*:*:*", "a wildcard part is a match expression, not a name"),
            ("cpe:2.3:-:apache:log4j:2.14.1:*:*:*:*:*:*:*", "nor is an NA part"),
            ("cpe:/", "2.2 with no part at all"),
            ("cpe:/:apache:log4j", "2.2 with an empty part"),
            ("cpe:2.2:a:apache:log4j:2.14.1:*:*:*:*:*:*:*", "no such formatted-string version"),
            ("https://example.test/cpe", "a URL, not a CPE"),
            ("just some text", "free text"),
        ],
    )
    def test_rejected(self, value, why):
        assert is_valid_cpe(value) is False, why

    def test_validate_raises_and_names_both_shapes(self):
        with pytest.raises(CPEValidationError) as exc:
            validate_cpe("not-a-cpe")

        message = str(exc.value)
        assert "2.3" in message
        assert "2.2" in message

    def test_an_unescaped_colon_does_not_pass_as_an_extra_field(self):
        """A stray colon splits the string, which is the common paste error."""
        assert is_valid_cpe("cpe:2.3:a:vendor:product:name:1.0:*:*:*:*:*:*:*") is False


class TestSchemaIntegration:
    """The mixin is where a malformed value would otherwise reach the database."""

    def test_a_malformed_cpe_is_rejected(self):
        import pydantic

        from sbomify.apps.core.schemas import ProductIdentifierCreateSchema

        with pytest.raises(pydantic.ValidationError, match="well-formed CPE"):
            ProductIdentifierCreateSchema(identifier_type="cpe", value="apache:log4j:2.14.1")

    def test_a_valid_cpe_is_kept_and_trimmed(self):
        from sbomify.apps.core.schemas import ProductIdentifierCreateSchema

        schema = ProductIdentifierCreateSchema(identifier_type="cpe", value=f" {LOG4J_23} ")

        assert schema.value == LOG4J_23

    def test_other_identifier_types_are_untouched(self):
        """Only the cpe branch is new; an SKU is still free-form."""
        from sbomify.apps.core.schemas import ProductIdentifierCreateSchema

        schema = ProductIdentifierCreateSchema(identifier_type="sku", value="ACME-123")

        assert schema.value == "ACME-123"

    def test_purl_still_gets_its_version_stripped(self):
        from sbomify.apps.core.schemas import ProductIdentifierCreateSchema

        schema = ProductIdentifierCreateSchema(identifier_type="purl", value="pkg:pypi/django@5.1.4")

        assert schema.value == "pkg:pypi/django"

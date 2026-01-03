"""Unit tests for the license loader module."""

import pytest
from sbomify.apps.core.licensing_utils import is_license_expression
from ..loader import get_license_list, validate_expression

def test_get_license_list():
    """Test that get_license_list returns all licenses with correct structure."""
    licenses = get_license_list()

    # Should have at least 520 items (500+ SPDX + custom licenses)
    assert len(licenses) >= 520

    # Check structure - separate SPDX and custom licenses
    spdx_licenses = [l for l in licenses if l["origin"] == "SPDX"]
    custom_licenses = [l for l in licenses if l["origin"] != "SPDX"]

    # Check SPDX license structure (should not have category field at all)
    if spdx_licenses:
        spdx_license = spdx_licenses[0]
        assert "key" in spdx_license
        assert "name" in spdx_license
        assert "origin" in spdx_license
        assert spdx_license["origin"] == "SPDX"
        # SPDX licenses should not have category field at all
        assert "category" not in spdx_license

    # Check that custom licenses are included and have category
    assert len(custom_licenses) >= 2  # At least Commons-Clause and BUSL-1.1
    assert any(l["key"] == "Commons-Clause" for l in custom_licenses)
    assert any(l["key"] == "BUSL-1.1" for l in custom_licenses)

    # Custom licenses should have category
    for custom_license in custom_licenses:
        assert "key" in custom_license
        assert "name" in custom_license
        assert "category" in custom_license
        assert custom_license["category"] is not None
        assert "origin" in custom_license
        assert custom_license["origin"] != "SPDX"


def test_expanded_custom_licenses():
    """Test that all expanded custom licenses are loaded correctly."""
    licenses = get_license_list()

    # Get all non-SPDX licenses (including various origins)
    custom_licenses = [l for l in licenses if l["origin"] != "SPDX"]
    assert len(custom_licenses) == 10  # Should have exactly 10 custom licenses

    # Check for specific custom licenses with various origins
    license_keys = {l["key"]: l for l in custom_licenses}

    assert "ELv2" in license_keys
    assert license_keys["ELv2"]["origin"] == "Elastic"
    assert license_keys["ELv2"]["name"] == "Elastic License 2.0"

    assert "SSPL-1.0" in license_keys
    assert license_keys["SSPL-1.0"]["origin"] == "MongoDB"

    assert "CCL-1.0" in license_keys
    assert license_keys["CCL-1.0"]["origin"] == "Confluent"

    assert "Timescale-License" in license_keys
    assert license_keys["Timescale-License"]["origin"] == "Timescale"


def test_validate_expression_with_new_custom_licenses():
    """Test validation of expressions with newly added custom licenses."""
    # Test with Elastic License
    result = validate_expression("Apache-2.0 OR ELv2")
    assert result["status"] == 200
    assert "Apache-2.0" in result["normalized"]
    assert "ELv2" in result["normalized"]
    assert len(result["tokens"]) == 2
    assert not result["unknown_tokens"]

    # Test with MongoDB SSPL
    result = validate_expression("MIT AND SSPL-1.0")
    assert result["status"] == 200
    assert "MIT" in result["normalized"]
    assert "SSPL-1.0" in result["normalized"]
    assert len(result["tokens"]) == 2
    assert not result["unknown_tokens"]

    # Test complex expression with multiple custom licenses
    result = validate_expression("(Apache-2.0 OR MIT) AND (ELv2 OR CCL-1.0)")
    assert result["status"] == 200
    assert len(result["tokens"]) == 4
    assert not result["unknown_tokens"]


def test_validate_expression_valid():
    """Test validation of valid license expressions."""
    # Test simple valid expression
    result = validate_expression("Apache-2.0")
    assert result["status"] == 200
    assert result["normalized"] == "Apache-2.0"
    assert len(result["tokens"]) == 1
    assert not result["unknown_tokens"]

    # Test complex valid expression with custom license
    result = validate_expression("Apache-2.0 WITH Commons-Clause OR MIT")
    assert result["status"] == 200
    assert "Apache-2.0" in result["normalized"]
    assert "Commons-Clause" in result["normalized"]
    assert "MIT" in result["normalized"]
    assert len(result["tokens"]) == 3
    assert not result["unknown_tokens"]

def test_validate_expression_unknown_token():
    """Test validation of expressions with unknown tokens."""
    result = validate_expression("FooBar-1.0")
    assert result["status"] == 200
    assert result["normalized"] == "FooBar-1.0"
    assert len(result["tokens"]) == 1
    assert result["unknown_tokens"] == ["FooBar-1.0"]

def test_validate_expression_syntax_error():
    """Test validation of expressions with syntax errors."""
    result = validate_expression("Apache-2.0 AND (")
    assert result["status"] == 400
    assert "error" in result
    assert "processing error" in result["error"].lower()


def test_is_license_expression():
    """Test the is_license_expression helper function."""
    # Simple license IDs should not be expressions
    assert not is_license_expression("MIT")
    assert not is_license_expression("Apache-2.0")
    assert not is_license_expression("GPL-3.0-only")

    # Expressions with OR operator
    assert is_license_expression("MIT OR Apache-2.0")
    assert is_license_expression("(MIT OR Apache-2.0)")
    assert is_license_expression("MIT or Apache-2.0")  # Case insensitive

    # Expressions with AND operator
    assert is_license_expression("MIT AND Apache-2.0")
    assert is_license_expression("(MIT AND Apache-2.0) AND GPL-3.0")

    # Expressions with WITH operator
    assert is_license_expression("Apache-2.0 WITH Commons-Clause")
    assert is_license_expression("GPL-3.0 WITH Classpath-exception-2.0")

    # Complex expressions
    assert is_license_expression("MIT OR (Apache-2.0 AND GPL-3.0)")
    assert is_license_expression(
        "(MIT OR Apache-2.0) AND (GPL-3.0 WITH Classpath-exception-2.0)"
    )

    # Edge cases - should not match operators in license names
    # (assuming no real license names contain these operators)
    assert not is_license_expression("")
    assert not is_license_expression(None)  # type: ignore
    assert not is_license_expression("MIT-AND-LICENSE")  # No word boundary match
"""Unit tests for the license loader module."""

import pytest
from ..loader import get_license_list, validate_expression

def test_get_license_list():
    """Test that get_license_list returns all licenses with correct structure."""
    licenses = get_license_list()

    # Should have at least 520 items (500+ SPDX + custom licenses)
    assert len(licenses) >= 520

    # Check structure of first license
    first_license = licenses[0]
    assert "key" in first_license
    assert "name" in first_license
    assert "category" in first_license
    assert "origin" in first_license
    assert first_license["origin"] in ["SPDX", "Custom"]

    # Check that custom licenses are included
    custom_licenses = [l for l in licenses if l["origin"] == "Custom"]
    assert len(custom_licenses) >= 2  # At least Commons-Clause and BUSL-1.1
    assert any(l["key"] == "Commons-Clause" for l in custom_licenses)
    assert any(l["key"] == "BUSL-1.1" for l in custom_licenses)


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
    assert "invalid" in result["error"].lower()
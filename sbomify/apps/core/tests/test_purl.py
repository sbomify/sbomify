"""Tests for PURL parsing and qualifier utilities."""

from __future__ import annotations

from sbomify.apps.core.purl import (
    canonicalize_qualifiers,
    extract_purl_qualifiers,
)


class TestCanonicalizeQualifiers:
    def test_sorts_keys(self) -> None:
        result = canonicalize_qualifiers({"distro": "jessie", "arch": "arm64"})
        assert list(result.keys()) == ["arch", "distro"]
        assert result == {"arch": "arm64", "distro": "jessie"}

    def test_lowercases_keys(self) -> None:
        result = canonicalize_qualifiers({"Arch": "arm64", "DISTRO": "jessie"})
        assert result == {"arch": "arm64", "distro": "jessie"}

    def test_removes_empty_values(self) -> None:
        result = canonicalize_qualifiers({"arch": "arm64", "distro": "", "os": ""})
        assert result == {"arch": "arm64"}

    def test_empty_input(self) -> None:
        assert canonicalize_qualifiers({}) == {}

    def test_preserves_value_case(self) -> None:
        result = canonicalize_qualifiers({"arch": "ARM64"})
        assert result == {"arch": "ARM64"}


class TestExtractPurlQualifiers:
    def test_valid_purl_with_qualifiers(self) -> None:
        purl = "pkg:deb/debian/curl@7.50.3-1?arch=arm64&distro=jessie"
        result = extract_purl_qualifiers(purl)
        assert result == {"arch": "arm64", "distro": "jessie"}

    def test_valid_purl_without_qualifiers(self) -> None:
        purl = "pkg:npm/@scope/package@1.0.0"
        result = extract_purl_qualifiers(purl)
        assert result == {}

    def test_invalid_purl(self) -> None:
        result = extract_purl_qualifiers("not-a-purl")
        assert result == {}

    def test_empty_string(self) -> None:
        result = extract_purl_qualifiers("")
        assert result == {}

    def test_qualifiers_are_canonicalized(self) -> None:
        purl = "pkg:deb/debian/curl@7.50.3-1?distro=jessie&arch=arm64"
        result = extract_purl_qualifiers(purl)
        assert list(result.keys()) == ["arch", "distro"]

    def test_single_qualifier(self) -> None:
        purl = "pkg:deb/debian/curl@7.50.3-1?arch=amd64"
        result = extract_purl_qualifiers(purl)
        assert result == {"arch": "amd64"}

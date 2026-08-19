"""Parsing of artifact content, which is supplier-controlled and often malformed.

`get_sbom_packages` reads documents uploaded by third parties — frequently
machine-generated, occasionally by tools that emit shapes the spec permits but
nobody expects. A parser that raises on those turns one bad dependency into a
tool that cannot answer at all, so the shapes tested here are the ones seen in
real CycloneDX output rather than hypotheticals.
"""

from __future__ import annotations

import pytest

from sbomify.apps.mcp.tools.artifacts import _bounded, _extract_packages, _license_label


class TestLicenseLabel:
    """Regression: chained `.get("license", {}).get(...)` raised AttributeError.

    A default only applies when the key is *absent*, so `{"license": null}` —
    which is valid JSON and appears in the wild — returned None and then blew up
    on the next `.get`.
    """

    def test_license_id(self):
        assert _license_label({"license": {"id": "MIT"}}) == "MIT"

    def test_license_name_when_no_id(self):
        assert _license_label({"license": {"name": "Custom Licence"}}) == "Custom Licence"

    def test_expression(self):
        assert _license_label({"expression": "MIT OR Apache-2.0"}) == "MIT OR Apache-2.0"

    @pytest.mark.parametrize(
        "entry",
        [
            {"license": None},
            {"license": []},
            {"license": "MIT-as-a-bare-string"},
            {"license": {}},
            {"license": {"id": None}},
            {},
            {"expression": None},
            {"license": {"id": 42}},
        ],
    )
    def test_malformed_entries_do_not_raise(self, entry):
        result = _license_label(entry)
        assert result is None or isinstance(result, str)

    def test_bare_string_license_is_used(self):
        assert _license_label({"license": "MIT-as-a-bare-string"}) == "MIT-as-a-bare-string"


class TestExtractPackages:
    def test_cyclonedx_with_a_null_license_still_parses(self):
        """The whole document must survive one malformed licence entry."""
        payload = {
            "components": [
                {"name": "good", "version": "1.0", "licenses": [{"license": {"id": "MIT"}}]},
                {"name": "malformed", "version": "2.0", "licenses": [{"license": None}]},
                {"name": "bare-string", "version": "3.0", "licenses": [{"license": "MIT"}]},
            ]
        }

        packages = _extract_packages(payload, "cyclonedx")

        assert [p["name"] for p in packages] == ["good", "malformed", "bare-string"]
        assert packages[0]["licenses"] == ["MIT"]
        assert packages[1]["licenses"] == []

    def test_non_dict_entries_are_skipped(self):
        payload = {"components": ["a string where an object was expected", None, {"name": "real"}]}

        assert [p["name"] for p in _extract_packages(payload, "cyclonedx")] == ["real"]

    def test_spdx_packages(self):
        payload = {
            "packages": [
                {
                    "name": "lib",
                    "versionInfo": "1.2.3",
                    "licenseDeclared": "Apache-2.0",
                    "externalRefs": [{"referenceType": "purl", "referenceLocator": "pkg:pypi/lib@1.2.3"}],
                },
                {"name": "unknown-licence", "versionInfo": "9", "licenseDeclared": "NOASSERTION"},
            ]
        }

        packages = _extract_packages(payload, "spdx")

        assert packages[0]["purl"] == "pkg:pypi/lib@1.2.3"
        assert packages[0]["licenses"] == ["Apache-2.0"]
        # NOASSERTION carries no information; reporting it as a licence would be
        # worse than reporting none.
        assert packages[1]["licenses"] == []


class TestBounded:
    def test_truncates_values(self):
        result = _bounded({"summary": "x" * 5000}, limit=100)

        assert result["summary"].endswith("[truncated by sbomify]")
        assert len(result["summary"]) < 200

    def test_truncates_keys(self):
        """Keys come from artifact content too, so they need the same cap."""
        result = _bounded({"y" * 5000: "value"}, limit=100)

        key = next(iter(result))
        assert key.endswith("[truncated by sbomify]")
        assert len(key) < 200
        assert result[key] == "value"

    def test_recurses_into_nested_structures(self):
        result = _bounded({"a": [{"b": "z" * 5000}]}, limit=100)

        assert result["a"][0]["b"].endswith("[truncated by sbomify]")

    def test_leaves_non_strings_alone(self):
        payload = {"count": 7, "ok": True, "missing": None}

        assert _bounded(payload) == payload

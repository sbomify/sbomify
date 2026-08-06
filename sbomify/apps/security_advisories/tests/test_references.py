"""The advisory-id link registry.

Each URL here was checked against a real id and an invalid one before being
added. The tests pin the shapes so a later edit cannot quietly point a scheme at
the wrong host, and pin the exclusions so an unverified scheme is not added
without someone noticing the deliberate gap.
"""

from __future__ import annotations

import pytest

from sbomify.apps.security_advisories.references import advisory_url


class TestResolvedSchemes:
    @pytest.mark.parametrize(
        ("identifier", "expected"),
        [
            ("CVE-2021-44228", "https://www.cve.org/CVERecord?id=CVE-2021-44228"),
            ("GHSA-jfh8-c2jp-5v3q", "https://github.com/advisories/GHSA-jfh8-c2jp-5v3q"),
            ("PYSEC-2021-19", "https://osv.dev/vulnerability/PYSEC-2021-19"),
            ("RUSTSEC-2021-0079", "https://osv.dev/vulnerability/RUSTSEC-2021-0079"),
            ("GO-2021-0113", "https://osv.dev/vulnerability/GO-2021-0113"),
            ("DSA-5020-1", "https://osv.dev/vulnerability/DSA-5020-1"),
            ("USN-5192-1", "https://osv.dev/vulnerability/USN-5192-1"),
            ("MAL-2024-9506", "https://osv.dev/vulnerability/MAL-2024-9506"),
            ("OSV-2021-1234", "https://osv.dev/vulnerability/OSV-2021-1234"),
        ],
    )
    def test_scheme_resolves_to_its_authoritative_page(self, identifier, expected):
        assert advisory_url(identifier) == expected

    def test_cert_note_drops_the_vu_prefix(self):
        """CERT/CC keys its notes on the bare number, so the prefix must go."""
        assert advisory_url("VU#930724") == "https://kb.cert.org/vuls/id/930724"

    def test_surrounding_whitespace_is_ignored(self):
        assert advisory_url("  CVE-2021-44228  ") == "https://www.cve.org/CVERecord?id=CVE-2021-44228"


class TestUnresolvedIdentifiers:
    """An id we cannot place renders as plain text rather than a guessed link."""

    @pytest.mark.parametrize(
        "identifier",
        [
            "",
            "   ",
            None,
            "ACME-2026-1",
            "just some text",
            "VU#",
        ],
    )
    def test_returns_empty(self, identifier):
        assert advisory_url(identifier) == ""

    @pytest.mark.parametrize("identifier", ["EUVD-2025-0001", "RHSA-2021:5126", "ZDI-21-1381", "EDB-50592"])
    def test_unverified_schemes_stay_plain(self, identifier):
        """These are recognised by detect_reference_type but have no verified URL.

        OSV holds no record for the vendor errata, and the remaining hosts would
        not answer a reachability check, so linking them would be a guess.
        """
        assert advisory_url(identifier) == ""


def test_every_registry_entry_is_a_https_url():
    from sbomify.apps.security_advisories.references import _ADVISORY_URLS

    assert all(url.startswith("https://") and "{id}" in url for url in _ADVISORY_URLS.values())

"""The advisory-id link registry.

Insights is checked against a canonical id and an id it does not hold, which it
answers with a 404; each external URL was checked against a real id and an
invalid one before being added. The tests pin the shapes so a later edit cannot quietly point a scheme at
the wrong host, and pin the exclusions so an unverified scheme is not added
without someone noticing the deliberate gap.
"""

from __future__ import annotations

import pytest

from sbomify.apps.security_advisories.references import advisory_url, insights_url


class TestResolvedSchemes:
    @pytest.mark.parametrize(
        ("identifier", "expected"),
        [
            ("CVE-2021-44228", "https://insights.sbomify.com/CVE-2021-44228/"),
            ("GHSA-6q48-6c7w-9gw2", "https://insights.sbomify.com/GHSA-6q48-6c7w-9gw2/"),
            ("PYSEC-2024-1", "https://insights.sbomify.com/PYSEC-2024-1/"),
            ("RUSTSEC-2026-0379", "https://insights.sbomify.com/RUSTSEC-2026-0379/"),
            ("GO-2021-0113", "https://insights.sbomify.com/GO-2021-0113/"),
            ("MAL-2024-9506", "https://insights.sbomify.com/MAL-2024-9506/"),
            ("OSV-2021-1234", "https://insights.sbomify.com/OSV-2021-1234/"),
            ("DSA-5020-1", "https://osv.dev/vulnerability/DSA-5020-1"),
            ("USN-5192-1", "https://osv.dev/vulnerability/USN-5192-1"),
        ],
    )
    def test_scheme_resolves_to_its_page(self, identifier, expected):
        assert advisory_url(identifier) == expected

    @pytest.mark.parametrize(
        ("identifier", "expected"),
        [
            ("cve-2021-44228", "https://insights.sbomify.com/CVE-2021-44228/"),
            ("ghsa-6Q48-6C7W-9GW2", "https://insights.sbomify.com/GHSA-6q48-6c7w-9gw2/"),
            ("mal-2024-9506", "https://insights.sbomify.com/MAL-2024-9506/"),
        ],
    )
    def test_insights_path_is_the_id_as_insights_spells_it(self, identifier, expected):
        assert insights_url(identifier) == expected

    @pytest.mark.parametrize(
        "identifier",
        ["CVE-", "CVE-2021-44228 and more", "CVE-2021-44228/../admin", "DSA-5020-1", "VU#930724", "RHSA-2021:5126"],
    )
    def test_insights_does_not_guess(self, identifier):
        assert insights_url(identifier) == ""

    def test_cert_note_drops_the_vu_prefix(self):
        """CERT/CC keys its notes on the bare number, so the prefix must go."""
        assert advisory_url("VU#930724") == "https://kb.cert.org/vuls/id/930724"

    def test_surrounding_whitespace_is_ignored(self):
        assert advisory_url("  CVE-2021-44228  ") == "https://insights.sbomify.com/CVE-2021-44228/"


class TestAliases:
    """Insights files a vulnerability under its CVE, so a CVE alias decides the page."""

    def test_cve_alias_wins_over_the_finding_id(self):
        assert (
            advisory_url("GHSA-jfh8-c2jp-5v3q", ["CVE-2021-44228"]) == "https://insights.sbomify.com/CVE-2021-44228/"
        )

    def test_cve_alias_gives_a_distro_id_an_insights_page(self):
        assert advisory_url("DSA-5020-1", ["CVE-2021-44228"]) == "https://insights.sbomify.com/CVE-2021-44228/"

    def test_comma_separated_aliases(self):
        assert (
            advisory_url("USN-5192-1", "DSA-5020-1,CVE-2021-44228") == "https://insights.sbomify.com/CVE-2021-44228/"
        )

    def test_a_cve_id_keeps_its_own_page(self):
        assert advisory_url("CVE-2021-44228", ["CVE-2021-45046"]) == "https://insights.sbomify.com/CVE-2021-44228/"

    def test_no_cve_alias_keeps_the_id(self):
        assert advisory_url("GHSA-6q48-6c7w-9gw2", ["PYSEC-2024-1"]) == "https://insights.sbomify.com/GHSA-6q48-6c7w-9gw2/"

    def test_a_malformed_cve_alias_is_skipped(self):
        assert advisory_url("GHSA-6q48-6c7w-9gw2", ["CVE-", "CVE-2021-44228"]) == (
            "https://insights.sbomify.com/CVE-2021-44228/"
        )


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
    from sbomify.apps.security_advisories.references import _ADVISORY_URLS, _INSIGHTS_SCHEMES

    assert all(url.startswith("https://") and "{id}" in url for url in _ADVISORY_URLS.values())
    assert not _INSIGHTS_SCHEMES & _ADVISORY_URLS.keys()

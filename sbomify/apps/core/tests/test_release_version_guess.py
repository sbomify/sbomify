"""Which release a new version most likely replaces, across the versioning schemes products actually use.

The create form preselects this guess and the user confirms it, so a wrong
guess costs a click. The rules the cases pin down:

- The guess is the highest existing version below the new one. That keeps a
  backport on its own line: 1.1.5 replaces 1.1.4 even when 2.0.0 shipped later.
- Release dates and the order releases arrive in play no part.
- A prerelease is never guessed, and a new prerelease gets no guess.
- Versions are compared only with versions carrying the same prefix, so
  ``api-v2.3.1`` never replaces ``web-v2.4.0``.
- When a version cannot be ordered (a codename, a commit hash, a Go
  pseudo-version), or two releases tie for the top, there is no guess.
"""

from itertools import permutations

import pytest

from sbomify.apps.core.services.release_versions import likely_predecessor


def guess(existing: list[str], new: str) -> str | None:
    return likely_predecessor(new, [(version, version) for version in existing])


def check(cases: list) -> pytest.MarkDecorator:
    return pytest.mark.parametrize(("existing", "new", "expected"), cases)


@check(
    [
        pytest.param(["1.2.2", "1.2.3"], "1.2.4", "1.2.3", id="patch"),
        pytest.param(["1.1.9", "1.2.3"], "1.3.0", "1.2.3", id="minor"),
        pytest.param(["1.9.5"], "2.0.0", "1.9.5", id="major-the-user-picks-the-line"),
        pytest.param(["1.2.9", "1.2.10"], "1.2.11", "1.2.10", id="numeric-not-lexical-patch"),
        pytest.param(["1.9.0", "1.10.0"], "1.11.0", "1.10.0", id="numeric-not-lexical-minor"),
        pytest.param(["1.1.4", "1.2.3", "2.0.0"], "1.1.5", "1.1.4", id="backport-to-the-oldest-line"),
        pytest.param(["1.1.4", "1.2.3", "2.0.0"], "1.2.4", "1.2.3", id="backport-to-a-middle-line"),
        pytest.param(["1.0.9", "1.2.3"], "1.1.0", "1.0.9", id="new-minor-between-lines"),
        pytest.param(["v1.2.3", "1.2.2"], "1.2.4", "v1.2.3", id="v-prefix-on-the-candidate"),
        pytest.param(["1.2.3"], "V1.2.4", "1.2.3", id="capital-v-prefix"),
        pytest.param(["v1.2.3", "1.2.2"], "1.2.3", "1.2.2", id="same-version-spelled-differently"),
        pytest.param(["1.2", "1.1.9"], "1.2.0", "1.1.9", id="two-and-three-parts-are-equal"),
        pytest.param(["1.2.0"], "1.2.0.1", "1.2.0", id="extra-part"),
        pytest.param(["1.9.5", "2.0.0-rc.2"], "2.0.0", "1.9.5", id="prerelease-candidate-skipped"),
        pytest.param(["1.0.0+build.1", "0.9.0"], "1.0.0+build.2", "1.0.0+build.1", id="rebuild"),
        pytest.param(["1.0.0+20130313144700"], "1.0.1+exp.sha.5114f85", "1.0.0+20130313144700", id="build-metadata"),
        pytest.param(["0.14.2", "0.15.0"], "0.15.1", "0.15.0", id="zerover"),
        pytest.param(["0.9.0"], "0.10.0", "0.9.0", id="zerover-minor-rollover"),
        pytest.param(["2.0.0"], "1.0.0", None, id="nothing-lower"),
        pytest.param([], "1.0.0", None, id="no-releases"),
        pytest.param([" 1.2.3 "], "1.2.4\n", " 1.2.3 ", id="surrounding-whitespace"),
    ]
)
def test_semver(existing: list[str], new: str, expected: str | None) -> None:
    assert guess(existing, new) == expected


@check(
    [
        pytest.param(["2.0.0", "1.9.5"], "2.1.0-rc.1", None, id="semver-rc"),
        pytest.param(["2.0.0"], "2.1.0-alpha.10", None, id="semver-alpha"),
        pytest.param(["2.0.0"], "2.1.0-beta", None, id="semver-beta-without-a-number"),
        pytest.param(["3.12.0", "3.11.7"], "3.13.0rc1", None, id="pep440-rc"),
        pytest.param(["3.12.0"], "3.13.0a1", None, id="pep440-alpha"),
        pytest.param(["3.12.0"], "3.13.0b2", None, id="pep440-beta"),
        pytest.param(["3.12.0"], "3.13.0.dev1", None, id="pep440-dev"),
        pytest.param(["5.2.9.RELEASE"], "5.3.0.M1", None, id="maven-milestone"),
        pytest.param(["0.9"], "1.0-SNAPSHOT", None, id="maven-snapshot"),
        pytest.param(["2.0", "1.9"], "2.1~beta1", None, id="debian-tilde"),
    ]
)
def test_a_prerelease_gets_no_guess(existing: list[str], new: str, expected: str | None) -> None:
    assert guess(existing, new) == expected


@check(
    [
        pytest.param(["v26.10.0", "v26.11.0"], "v26.11.1", "v26.11.0", id="sbomify-patch"),
        pytest.param(["v26.9.0", "v26.10.0"], "v26.11.0", "v26.10.0", id="sbomify-month-rollover"),
        pytest.param(["v26.12.0"], "v27.1.0", "v26.12.0", id="sbomify-year-rollover"),
        pytest.param(["24.11.0", "24.11.1"], "24.11.2", "24.11.1", id="sentry-micro"),
        pytest.param(["24.12.1"], "25.1.0", "24.12.1", id="sentry-year-rollover"),
        pytest.param(["23.10", "24.04"], "24.10", "24.04", id="ubuntu-zero-padded-month"),
        pytest.param(["22.04.4", "24.04", "24.04.1"], "22.04.5", "22.04.4", id="ubuntu-point-release-after-next-lts"),
        pytest.param(["24.04 LTS", "23.10"], "24.10", "24.04 LTS", id="ubuntu-lts-label"),
        pytest.param(["2024.07.04", "2024.08.30"], "2024.12.14", "2024.08.30", id="yyyy-mm-dd"),
        pytest.param(["2024.12.06"], "2024.12.06.1", "2024.12.06", id="yyyy-mm-dd-micro"),
        pytest.param(["2024-04-10", "2024-06-20"], "2024-09-30", "2024-06-20", id="hyphenated-date"),
        pytest.param(["2024-06-20"], "2024-09-30.acacia", "2024-06-20", id="dated-api-version-with-a-name"),
        pytest.param(["20231114", "20240312"], "20240514", "20240312", id="yyyymmdd"),
        pytest.param(["microcode-20240312"], "microcode-20240514", "microcode-20240312", id="prefixed-yyyymmdd"),
        pytest.param(["2024.2.4", "2024.3"], "2024.3.1", "2024.3", id="jetbrains-year-minor-micro"),
        pytest.param(["2023d", "2024a"], "2024b", "2024a", id="tzdata-letter"),
        pytest.param(["2023d"], "2024a", "2023d", id="tzdata-year-rollover"),
        pytest.param(["21H2", "22H2"], "23H2", "22H2", id="windows-half-year"),
        pytest.param(["18.6", "18.7.1"], "26.0", "18.7.1", id="switch-to-year-major"),
        pytest.param(["8.4.6", "9.7.0"], "26.7.0", "9.7.0", id="switch-from-semver-to-year-month"),
        pytest.param(["3.4.1", "3.5.0"], "2024.1.0", "3.5.0", id="switch-from-semver-to-calver"),
        pytest.param(["2023.4", "2023.10"], "1.0.0", None, id="switch-from-calver-back-to-semver"),
        pytest.param(
            ["2026.04.13.0123abc", "2026.04.14.def5678"],
            "2026.04.15.abc1234",
            "2026.04.14.def5678",
            id="date-and-commit",
        ),
        pytest.param(
            ["2026.04.14.1a2b3c4", "2026.04.14.5d6e7f8"], "2026.04.15.abc1234", None, id="same-day-builds-tie"
        ),
        pytest.param(
            ["2026.04.14.def5678"], "2026.04.15.c0ffee1", "2026.04.14.def5678", id="a-commit-is-not-a-c-release"
        ),
        pytest.param(
            ["2026.04.14.7a1b2c3-v2", "2026.04.14.7a1b2c3-v3"],
            "2026.04.14.7a1b2c3-v4",
            "2026.04.14.7a1b2c3-v3",
            id="date-commit-and-rebuild",
        ),
    ]
)
def test_calver(existing: list[str], new: str, expected: str | None) -> None:
    assert guess(existing, new) == expected


@check(
    [
        pytest.param(["120.0.6099.109", "121.0.6167.85"], "120.0.6099.130", "120.0.6099.109", id="chrome-backport"),
        pytest.param(["120.0.6099.109", "121.0.6167.85"], "121.0.6167.139", "121.0.6167.85", id="chrome-patch"),
        pytest.param(["99", "100"], "101", "100", id="browser-major-past-100"),
        pytest.param(["9"], "10", "9", id="single-integer"),
        pytest.param(["1.0.0.0", "0.9.0"], "1.0.0.1", "1.0.0.0", id="nuget-revision"),
        pytest.param(["17.0.9", "21.0.1"], "21.0.2", "21.0.1", id="java-feature-update"),
        pytest.param(["17.0.9", "21.0.1"], "17.0.10", "17.0.9", id="java-lts-backport"),
        pytest.param(["21.0.1+12"], "21.0.2+13", "21.0.1+12", id="java-build-number"),
        pytest.param(["1.8.0_382", "1.8.0_392"], "1.8.0_401", "1.8.0_392", id="java-legacy-underscore"),
        pytest.param(["8u382", "8u392"], "8u401", "8u392", id="java-legacy-update"),
        pytest.param(["9.6.24", "10.23"], "11.0", "10.23", id="postgres-two-part-major"),
        pytest.param(["9.6.23", "10.22"], "9.6.24", "9.6.23", id="postgres-old-line"),
        pytest.param(["3.1415926", "3.14159265"], "3.141592653", "3.14159265", id="tex"),
        pytest.param(["2.718281"], "2.7182818", "2.718281", id="metafont"),
    ]
)
def test_four_part_monotonic_and_asymptotic(existing: list[str], new: str, expected: str | None) -> None:
    assert guess(existing, new) == expected


@check(
    [
        pytest.param(["3.12.0rc3", "3.11.7"], "3.12.0", "3.11.7", id="pep440-final-skips-its-rc"),
        pytest.param(["1.0", "1.0.post1"], "1.0.post2", "1.0.post1", id="pep440-post"),
        pytest.param(["0.9", "1.0"], "1.0.post1", "1.0", id="pep440-first-post"),
        pytest.param(["2024.1", "2024.2"], "1!1.0", "2024.2", id="pep440-epoch-beats-any-version"),
        pytest.param(["1!1.0", "2025.1"], "1!1.1", "1!1.0", id="pep440-within-an-epoch"),
        pytest.param(["5.2.9.RELEASE", "5.3.0.RELEASE"], "5.3.1.RELEASE", "5.3.0.RELEASE", id="maven-release"),
        pytest.param(["5.2.9.RELEASE", "5.3.0.RC2"], "5.3.0.RELEASE", "5.2.9.RELEASE", id="maven-release-skips-rc"),
        pytest.param(["5.3.9.Final", "5.4.0"], "5.4.0.Final", "5.3.9.Final", id="maven-final-equals-plain"),
        pytest.param(["1.0", "1.0-SP1"], "1.0-SP2", "1.0-SP1", id="maven-service-pack"),
        pytest.param(["1.9", "2.0~rc1"], "2.0", "1.9", id="debian-tilde-candidate-skipped"),
        pytest.param(["1:2.30-1", "2.40-1"], "1:2.31-1", "1:2.30-1", id="debian-epoch"),
        pytest.param(["2.36-8", "2.36-9"], "2.36-9+deb12u1", "2.36-9", id="debian-stable-update"),
        pytest.param(["2.36-9"], "2.36-10", "2.36-9", id="debian-revision"),
        pytest.param(["2.0"], "2.0^20250825", "2.0", id="rpm-caret-snapshot"),
        pytest.param(["2.0", "2.0^20250825"], "2.0.1", "2.0^20250825", id="rpm-caret-is-older-than-the-next"),
    ]
)
def test_ecosystem_grammars(existing: list[str], new: str, expected: str | None) -> None:
    assert guess(existing, new) == expected


@check(
    [
        pytest.param(["10.2.9", "10.2.9-h1", "11.0.0"], "10.2.9-h2", "10.2.9-h1", id="pan-os-hotfix"),
        pytest.param(["10.2.8-h3", "10.2.9"], "10.2.9-h1", "10.2.9", id="pan-os-first-hotfix"),
        pytest.param(["21.2R3-S6", "22.4R2-S2"], "21.2R3-S7", "21.2R3-S6", id="junos-service-release"),
        pytest.param(["22.4R2", "22.4R2-S2"], "22.4R3", "22.4R2-S2", id="junos-next-release"),
        pytest.param(["1.1.1v", "3.0.12"], "1.1.1w", "1.1.1v", id="openssl-letter-fix"),
        pytest.param(["1.1.1"], "1.1.1a", "1.1.1", id="a-lone-letter-is-a-fix-not-an-alpha"),
        pytest.param(["17.9.4", "17.12.2"], "17.9.4a", "17.9.4", id="ios-xe-rebuild"),
        pytest.param(["v1.0.4", "v1.0.5"], "v1.0.4-14-g2414721", "v1.0.4", id="git-describe"),
        pytest.param(["11", "12"], "12L", "12", id="android-12l"),
        pytest.param(["115.4.0esr", "128.0"], "115.5.0esr", "115.4.0esr", id="firefox-esr"),
    ]
)
def test_hotfix_and_letter_suffixes(existing: list[str], new: str, expected: str | None) -> None:
    assert guess(existing, new) == expected


@check(
    [
        pytest.param(["release-1.1.0", "release-1.2.0"], "release-1.3.0", "release-1.2.0", id="tag-prefix"),
        pytest.param(["api-v2.3.0", "web-v2.4.0"], "api-v2.3.1", "api-v2.3.0", id="monorepo-prefixes-kept-apart"),
        pytest.param(["web-v2.4.0"], "api-v2.3.1", None, id="no-release-with-the-same-prefix"),
        pytest.param(["MyApp 2.0", "MyApp 2.1"], "MyApp 2.2", "MyApp 2.1", id="product-name-and-space"),
        pytest.param(["myapp 2.1"], "MyApp 2.2", "myapp 2.1", id="prefix-ignores-case"),
        pytest.param(["sbomify-v26.8.0"], "sbomify-v26.9.0", "sbomify-v26.8.0", id="named-tag"),
        pytest.param(["v0.1"], "v.2", "v0.1", id="v-then-a-dot"),
        pytest.param(["Windows 10"], "Windows 11", "Windows 10", id="marketing-name"),
    ]
)
def test_prefixes(existing: list[str], new: str, expected: str | None) -> None:
    assert guess(existing, new) == expected


@check(
    [
        pytest.param(["bookworm", "bullseye"], "trixie", None, id="codenames"),
        pytest.param(["bookworm", "1.0.0"], "1.0.1", "1.0.0", id="codename-candidate-ignored"),
        pytest.param(["1.0.0"], "a1b2c3d4e5f6", None, id="commit-hash"),
        pytest.param(["a1b2c3d", "1.0.0"], "1.0.1", "1.0.0", id="commit-hash-candidate-ignored"),
        pytest.param(["v1.2.3"], "v1.2.4-0.20191109021931-daa7c04131f5", None, id="go-pseudo-version"),
        pytest.param(["latest"], "next", None, id="channel-names"),
        pytest.param(["1.0.0"], "", None, id="empty"),
        pytest.param(["v1.2.3", "1.2.3"], "1.2.4", None, id="two-releases-tie-for-the-top"),
    ]
)
def test_no_guess_when_the_version_cannot_be_ordered(existing: list[str], new: str, expected: str | None) -> None:
    assert guess(existing, new) == expected


def test_the_order_releases_arrive_in_does_not_matter() -> None:
    # The view lists candidates newest first by date. The guess must not lean on that order.
    for order in permutations(["1.1.4", "1.2.3", "2.0.0", "2.0.1-rc.1"]):
        assert guess(list(order), "1.1.5") == "1.1.4"


def test_the_guess_is_the_candidate_key() -> None:
    assert likely_predecessor("1.2.4", [("rel-a", "1.2.3"), ("rel-b", "1.2.2")]) == "rel-a"

"""Which existing release a new version most likely replaces.

The create form preselects this guess and the user confirms it, so it only has
to be a good first guess. What a release replaces is still a declared edge;
version strings are read here for one reason, to save the user a click.

The guess is the highest version below the new one. Release dates play no
part: a backport, 1.1.5 shipped after 2.0.0, replaces 1.1.4, where a date
would say 2.0.0. A prerelease is never guessed and a new prerelease gets no
guess. Versions are compared only with versions carrying the same prefix, so a
monorepo's ``api-v2.3.1`` never replaces its ``web-v2.4.0``. A codename, a
commit hash or a Go pseudo-version cannot be ordered, so it gets no guess
rather than a wrong one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import NamedTuple

# Words that mark a version as not yet released, across SemVer, PEP 440, Maven and nightlies. A single
# letter counts only with a number after it (1.0a1), so OpenSSL's 1.1.1a stays a fix release.
_PRERELEASE = frozenset(
    {"a", "alpha", "b", "beta", "c", "rc", "cr", "pre", "preview", "dev", "snapshot", "m", "milestone", "ea", "nightly"}
)
# Labels naming the release itself: 5.4.0.Final is 5.4.0.
_SAME_RELEASE = frozenset({"final", "ga", "release", "stable", "lts"})

_EPOCH = re.compile(r"(\d+)[:!]")
_NUMBERS = re.compile(r"\d+(?:[._-]\d+)*")
_COMMIT = re.compile(r"(?=.*[a-f])(?=.*\d)[0-9a-f]{7,40}")
# A commit hash as one part of a version, as in 2026.04.14.1a2b3c4: it names a build but orders nothing.
_COMMIT_PART = re.compile(r"[._+-](?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?=$|[._+-])")
_GO_PSEUDO = re.compile(r"\d{14}-[0-9a-f]{12}$")
_TOKEN = re.compile(r"[a-z]+|\d+")

_Tail = tuple[tuple[int, int, str], ...]


class _Version(NamedTuple):
    prefix: str
    prerelease: bool
    order: tuple[int, tuple[int, ...], bool, _Tail]


def _parse(value: str) -> _Version | None:
    text = value.strip().lower()
    if _COMMIT.fullmatch(text) or _GO_PSEUDO.search(text):
        return None
    text = _COMMIT_PART.sub("", text)
    epoch = 0
    if match := _EPOCH.match(text):
        epoch, text = int(match.group(1)), text[match.end() :]
    numbers_match = _NUMBERS.search(text)
    if numbers_match is None:
        return None
    # A "v" before the number is spelling: v1.2.3 is 1.2.3, and sbomify-v26.8.0 has the prefix "sbomify".
    prefix = re.sub(r"(^|[^a-z])v$", r"\1", text[: numbers_match.start()].rstrip(" -_./")).strip(" -_./")
    numbers = [int(part) for part in re.split(r"[._-]", numbers_match.group())]
    while numbers and numbers[-1] == 0:
        numbers.pop()  # 1.2 and 1.2.0 are one version
    suffix = text[numbers_match.end() :]
    tokens = _TOKEN.findall(suffix)
    word = tokens[0] if tokens and tokens[0].isalpha() else ""
    prerelease = "~" in suffix or (word in _PRERELEASE and (len(word) > 1 or (len(tokens) > 1 and tokens[1].isdigit())))
    if tokens == [word] and word in _SAME_RELEASE:
        tokens = []
    # Anything else after the number sorts after it: a hotfix (10.2.9-h1), a letter fix (1.1.1w), a rebuild
    # (2.36-9+deb12u1). A number in it compares as a number and above a word, as Maven and RPM do.
    tail = tuple((1, int(token), "") if token.isdigit() else (0, 0, token) for token in tokens)
    return _Version(prefix, prerelease, (epoch, tuple(numbers), bool(tail), tail))


def likely_predecessor[K](version: str, candidates: Iterable[tuple[K, str]]) -> K | None:
    """The key of the candidate a release ``version`` most likely replaces, or None when the versions do not say.

    ``candidates`` pairs each existing release's key with its version string. Their order does not matter, so
    two releases tying for the top get no guess rather than the first one listed.
    """
    new = _parse(version)
    if new is None or new.prerelease:
        return None
    below = [
        (old.order, key)
        for key, text in candidates
        if (old := _parse(text)) and not old.prerelease and old.prefix == new.prefix and old.order < new.order
    ]
    if not below:
        return None
    top = max(order for order, _key in below)
    (best, *tied) = [key for order, key in below if order == top]
    return None if tied else best

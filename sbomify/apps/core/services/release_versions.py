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

Maven's comparator, from univers, does the ordering. It reads no scheme in
particular: it splits on separators and digit-letter changes, compares numbers
as numbers, ranks alpha, beta, milestone, rc and snapshot below the release,
treats final, ga and release as the release itself, and sorts anything else
after it, which covers hotfixes (10.2.9-h1), letter fixes (1.1.1w) and
rebuilds (2.36-9+deb12u1). What it leaves out is handled here: epochs, a
Debian tilde, PEP 440's dev, prefixes, commit hashes and Go pseudo-versions.
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import groupby, takewhile
from string import digits, hexdigits
from typing import NamedTuple

from univers.versions import InvalidVersion, MavenVersion

# Words marking a prerelease that Maven's comparator sorts after the release instead.
_MORE_PRERELEASE_WORDS = frozenset({"dev", "pre", "preview", "nightly"})
_SEPARATORS = " ._-+/"


class _Version(NamedTuple):
    prefix: str
    prerelease: bool
    order: tuple[int, MavenVersion]


def _is_commit(text: str) -> bool:
    """Whether ``text`` looks like a commit hash: 7 to 40 hex characters mixing letters and digits."""
    return 7 <= len(text) <= 40 and all(c in hexdigits for c in text) and not text.isdigit() and not text.isalpha()


def _is_go_pseudo_version(text: str) -> bool:
    """Whether ``text`` is a Go pseudo-version, vX.Y.Z-[pre.]yyyymmddhhmmss-abcdefabcdef, which only Go orders."""
    parts = text.split("-")
    if len(parts) < 3 or len(parts[-1]) != 12 or not all(c in hexdigits for c in parts[-1]):
        return False
    stamp = parts[-2].rpartition(".")[2]
    return len(stamp) == 14 and stamp.isdigit()


def _without_commits(text: str) -> str:
    """``text`` without a commit hash written as one dotted part, as in 2026.04.14.1a2b3c4.

    The hash names a build and orders nothing. A rebuild counter after it, as in 1a2b3c4-v2, stays.
    """
    kept: list[str] = []
    for part in text.split("."):
        head, dash, rest = part.partition("-")
        if not _is_commit(head):
            kept.append(part)
        elif rest and kept:
            kept[-1] += dash + rest
    return ".".join(kept)


def _split_epoch(text: str) -> tuple[int, str]:
    """Debian's 1:2.30 and PEP 440's 1!2.0 lead with an epoch, which outranks any version without one."""
    for mark in (":", "!"):
        head, found, rest = text.partition(mark)
        if found and head.isdigit():
            return int(head), rest
    return 0, text


def _parse(value: str) -> _Version | None:
    text = value.strip().lower()
    if _is_commit(text) or _is_go_pseudo_version(text):
        return None
    epoch, text = _split_epoch(_without_commits(text))
    prefix = "".join(takewhile(lambda c: not c.isdigit(), text))
    version = text[len(prefix) :]
    if not version:
        return None
    # A "v" before the number is spelling: v1.2.3 is 1.2.3, and sbomify-v26.8.0 has the prefix "sbomify".
    prefix = prefix.rstrip(_SEPARATORS)
    if prefix == "v" or (prefix.endswith("v") and prefix[-2] in _SEPARATORS):
        prefix = prefix[:-1].rstrip(_SEPARATORS)
    released = "".join(takewhile(lambda c: c in digits + "._-", version)).rstrip("._-")
    try:
        ordered, plain = MavenVersion(version), MavenVersion(released)
    except InvalidVersion:
        return None
    words = ["".join(run) for letters, run in groupby(version[len(released) :], str.isalpha) if letters]
    # Maven sorts 2.0.0-rc.1 below 2.0.0 by itself. A tilde and PEP 440's dev need saying.
    prerelease = ordered < plain or "~" in version or (bool(words) and words[0] in _MORE_PRERELEASE_WORDS)
    return _Version(prefix, prerelease, (epoch, ordered))


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
    best, *tied = [key for order, key in below if order == top]
    return None if tied else best

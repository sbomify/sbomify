"""Where an advisory identifier can be read in full.

The scheme vocabulary lives in :mod:`~sbomify.apps.security_advisories.models`
(:class:`ReferenceType`, :func:`detect_reference_type`); this maps the schemes we
can resolve onto a page, so a finding id renders as a link instead of an opaque
string.

sbomify Insights comes first. It publishes one page per vulnerability at a URL
built from the id alone (``https://insights.sbomify.com/<ID>/``), and folds every
advisory naming the same flaw into the CVE's page when there is one. So a finding
whose aliases include a CVE links to that CVE, and an id with no CVE behind it
links to its own page. Insights answers 404 for an id it does not hold, which is
what made each scheme in ``_INSIGHTS_SCHEMES`` checkable.

SUSE and openSUSE updates have a page of their own there. The Debian, Ubuntu
and CERT schemes have only an alias entry on the CVE's, so on their own they keep
the external host below. Every
external entry was checked against a live id **and** a deliberately invalid
one, because two of the candidate hosts serve their pages client-side and answer
200 for any path, which makes a naive reachability check meaningless. A scheme
whose URL could not be confirmed that way is deliberately absent: an
unrecognised id renders as plain text, which is the honest outcome, and adding
one later is a single row here.

Absent for that reason: EUVD, RHSA, ALSA, ALAS, ZDI, EDB, MSRC, JVNDB.
OSV has no record for the vendor-errata schemes, and the remaining hosts refused
the check rather than answering it.
"""

from __future__ import annotations

import string
from collections.abc import Iterable

from .models import ReferenceType, detect_reference_type

INSIGHTS_BASE_URL = "https://insights.sbomify.com"

_ALNUM = frozenset(string.ascii_letters + string.digits)
_ID_BODY_CHARS = _ALNUM | frozenset(":._")


def _is_id_shaped(identifier: str) -> bool:
    """A prefix and at least one more dash-separated part, nothing that would need
    escaping in a path. A bare "CVE-" or a sentence that starts with one is not an id.

    Checked part by part rather than with a regex: the id comes from uploaded SBOMs,
    and a nested quantifier over it backtracks polynomially on a long malformed one.
    """
    prefix, *parts = identifier.split("-")
    return (
        bool(prefix)
        and set(prefix) <= _ALNUM
        and bool(parts)
        and all(part and set(part) <= _ID_BODY_CHARS for part in parts)
    )


# The schemes Insights publishes a page for under the id itself.
_INSIGHTS_SCHEMES: frozenset[str] = frozenset(
    {
        ReferenceType.CVE,
        ReferenceType.GHSA,
        ReferenceType.OSV,
        ReferenceType.MAL,
        ReferenceType.PYSEC,
        ReferenceType.RUSTSEC,
        ReferenceType.GO,
        ReferenceType.SUSE,
    }
)

# Insights paths are case-sensitive, and openSUSE keeps its own spelling in them.
_INSIGHTS_PREFIX_SPELLING: dict[str, str] = {"OPENSUSE-": "openSUSE-"}

# OSV serves the ecosystem and distro schemes under one path, so they share a row
# rather than each carrying a near-identical URL.
_OSV = "https://osv.dev/vulnerability/{id}"

_ADVISORY_URLS: dict[str, str] = {
    ReferenceType.DSA: _OSV,
    ReferenceType.USN: _OSV,
    # CERT/CC keys its notes on the bare number, so "VU#930724" is trimmed below.
    ReferenceType.CERT_VU: "https://kb.cert.org/vuls/id/{id}",
}

_ID_PREFIX_TO_TRIM: dict[str, str] = {ReferenceType.CERT_VU: "VU#"}


def insights_url(identifier: str | None) -> str:
    """The Insights page for an advisory id, or "" for a scheme Insights does not publish.

    The path is the id as Insights spells it: upper case, except a GHSA's body,
    which GitHub writes in lower case, and openSUSE's prefix. A colon becomes a
    hyphen, as it does in every Insights path.
    """
    identifier = (identifier or "").strip()
    reference_type = detect_reference_type(identifier)
    if reference_type not in _INSIGHTS_SCHEMES or not _is_id_shaped(identifier):
        return ""
    if reference_type == ReferenceType.GHSA:
        path = "GHSA-" + identifier[len("GHSA-") :].lower()
    else:
        path = identifier.upper()
        for prefix, spelling in _INSIGHTS_PREFIX_SPELLING.items():
            if path.startswith(prefix):
                path = spelling + path[len(prefix) :]
    return f"{INSIGHTS_BASE_URL}/{path.replace(':', '-')}/"


def advisory_url(identifier: str | None, aliases: Iterable[str] | None = None) -> str:
    """The page for an advisory id, or "" when we cannot resolve it.

    ``aliases`` are the other ids the same finding is known by, as a list or a
    comma-separated string. When one of them is a CVE, that is the page Insights files the vulnerability under, so it
    wins over the id itself.

    Returning a string rather than raising keeps the call sites free of
    branching: a template asks for the URL and falls back to plain text when it
    is empty.
    """
    if not identifier:
        return ""
    identifier = identifier.strip()
    if not identifier:
        return ""

    if isinstance(aliases, str):
        aliases = aliases.split(",")
    if detect_reference_type(identifier) != ReferenceType.CVE:
        for alias in aliases or ():
            if isinstance(alias, str) and detect_reference_type(alias) == ReferenceType.CVE:
                if url := insights_url(alias):
                    return url

    if url := insights_url(identifier):
        return url

    reference_type = detect_reference_type(identifier)
    template = _ADVISORY_URLS.get(reference_type)
    if not template:
        return ""

    trim = _ID_PREFIX_TO_TRIM.get(reference_type)
    if trim and identifier.upper().startswith(trim):
        identifier = identifier[len(trim) :]
        if not identifier:
            return ""

    return template.format(id=identifier)

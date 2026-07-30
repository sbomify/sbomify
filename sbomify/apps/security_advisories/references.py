"""Where an advisory identifier can be read in full.

The scheme vocabulary lives in :mod:`~sbomify.apps.security_advisories.models`
(:class:`ReferenceType`, :func:`detect_reference_type`); this maps the schemes we
can resolve onto their authoritative page, so a finding id renders as a link
instead of an opaque string.

Every entry below was checked against a live id **and** a deliberately invalid
one, because two of the candidate hosts serve their pages client-side and answer
200 for any path, which makes a naive reachability check meaningless. A scheme
whose URL could not be confirmed that way is deliberately absent: an
unrecognised id renders as plain text, which is the honest outcome, and adding
one later is a single row here.

Absent for that reason: EUVD, RHSA, ALSA, ALAS, SUSE, ZDI, EDB, MSRC, JVNDB.
OSV has no record for the vendor-errata schemes, and the remaining hosts refused
the check rather than answering it.
"""

from __future__ import annotations

from .models import ReferenceType, detect_reference_type

# OSV serves the ecosystem and distro schemes under one path, so they share a row
# rather than each carrying a near-identical URL.
_OSV = "https://osv.dev/vulnerability/{id}"

_ADVISORY_URLS: dict[str, str] = {
    ReferenceType.CVE: "https://www.cve.org/CVERecord?id={id}",
    ReferenceType.GHSA: "https://github.com/advisories/{id}",
    ReferenceType.OSV: _OSV,
    ReferenceType.MAL: _OSV,
    ReferenceType.PYSEC: _OSV,
    ReferenceType.RUSTSEC: _OSV,
    ReferenceType.GO: _OSV,
    ReferenceType.DSA: _OSV,
    ReferenceType.USN: _OSV,
    # CERT/CC keys its notes on the bare number, so "VU#930724" is trimmed below.
    ReferenceType.CERT_VU: "https://kb.cert.org/vuls/id/{id}",
}

_ID_PREFIX_TO_TRIM: dict[str, str] = {ReferenceType.CERT_VU: "VU#"}


def advisory_url(identifier: str | None) -> str:
    """The authoritative page for an advisory id, or "" when we cannot resolve it.

    Returning a string rather than raising keeps the call sites free of
    branching: a template asks for the URL and falls back to plain text when it
    is empty.
    """
    if not identifier:
        return ""
    identifier = identifier.strip()
    if not identifier:
        return ""

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

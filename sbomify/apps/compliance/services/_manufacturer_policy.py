"""Shared manufacturer-name policy used by CRA artefact generators.

Single source of truth for the predicate that detects placeholder /
stub manufacturer names. Both ``document_generation_service`` (which
renders the Declaration of Conformity) and ``export_service`` (which
flags the bundle manifest) read this module so the two artefacts stay
in lockstep when the vocabulary changes.

CRA context: Annex V item 2 of Regulation (EU) 2024/2847 requires the
manufacturer's legal name on the EU Declaration of Conformity. This
guard is a UX-facing safety net, not a trust boundary — a determined
operator can still set ``"Tester GmbH"`` (not in the denylist) and
bypass it. Its job is to catch the common accidental case where the
team profile is left with an obvious stub ("ABC" / "xyz" / "test").
"""

from __future__ import annotations

# Placeholder / clearly-bogus manufacturer names. Case-insensitive
# equality match on the stripped value — the matcher intentionally
# does NOT do substring matching, because real companies contain
# these tokens ("Acme Labs", "Test Manufacturing Ltd.", etc.).
PLACEHOLDER_MANUFACTURER_VALUES: frozenset[str] = frozenset(
    {
        "",
        "abc",
        "xyz",
        "test",
        "example",
        "acme",
        "foo",
        "bar",
        "tbd",
        "todo",
        "n/a",
        "na",
        "none",
        "null",
    }
)


def is_placeholder_manufacturer(name: str | None) -> bool:
    """Return True when ``name`` looks like a placeholder / stub.

    ``None``, empty, whitespace-only, and any case-insensitive match
    against ``PLACEHOLDER_MANUFACTURER_VALUES`` count. Guards the DoC
    from rendering ``Manufacturer: ABC`` when the operator hasn't set
    up their team profile.
    """
    if not name:
        return True
    return name.strip().lower() in PLACEHOLDER_MANUFACTURER_VALUES

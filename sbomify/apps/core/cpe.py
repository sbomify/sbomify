"""CPE (Common Platform Enumeration) validation.

Covers both bindings a user can legitimately paste, per NIST IR 7695:

* the 2.3 formatted string, ``cpe:2.3:a:vendor:product:...`` with thirteen
  colon-separated fields;
* the older 2.2 URI, ``cpe:/a:vendor:product:...`` with up to seven.

Accepting 2.2 as well as 2.3 is deliberate. The identifier type is plain
``cpe``, published feeds still carry 2.2 URIs, and rejecting one would turn a
correct identifier into an error. Anything that is neither is malformed.

Pure functions, no Django, matching :mod:`sbomify.apps.core.purl`.
"""

from __future__ import annotations

import re

# A 2.3 field: ``*`` (ANY), ``-`` (NA), or a string where ``:`` and ``\`` only
# appear escaped, so a stray colon cannot silently split into a new field.
_CPE23_FIELD = r"(?:[*\-]|(?:[^:\\]|\\.)+)"
# ``part`` is the one attribute with a closed vocabulary: application, operating
# system, hardware. A wildcard part belongs to a matching expression, not to a
# name for a specific product, which is what an identifier records.
CPE23_PATTERN = re.compile(rf"^cpe:2\.3:[aoh]:(?:{_CPE23_FIELD}:){{9}}{_CPE23_FIELD}$")

# The 2.2 URI binding: cpe:/part:vendor:product:version:update:edition:language.
# The part is required for the same reason; everything after it is optional,
# which is how a short URI like ``cpe:/a:apache:log4j`` stays valid.
CPE22_PATTERN = re.compile(r"^cpe:/[aoh](?::[^:]*){0,6}$")


class CPEValidationError(ValueError):
    """Raised when a value is not a well-formed CPE in either binding."""


def is_valid_cpe(value: str) -> bool:
    """Whether ``value`` is a well-formed CPE 2.3 formatted string or 2.2 URI."""
    value = (value or "").strip()
    if not value:
        return False
    return bool(CPE23_PATTERN.match(value) or CPE22_PATTERN.match(value))


def validate_cpe(value: str) -> str:
    """Return the trimmed CPE, or raise :class:`CPEValidationError`.

    The message names both accepted shapes, because "invalid CPE" leaves the
    reader guessing which of the two they got wrong.
    """
    trimmed = (value or "").strip()
    if not is_valid_cpe(trimmed):
        raise CPEValidationError(
            f"{value!r} is not a well-formed CPE. Expected a 2.3 formatted string "
            f"(cpe:2.3:a:vendor:product:version:update:edition:language:sw_edition:"
            f"target_sw:target_hw:other) or a 2.2 URI (cpe:/a:vendor:product:version)."
        )
    return trimmed

"""Shared loaders for CRA reference data shipped alongside the app.

Centralises the path to ``reference_data/cra-harmonised-standards.json``
and the ``read_bytes`` / ``json.loads`` wrappers around it so the two
compliance services (document generation and export) don't maintain
parallel constants that can drift.

**Fail-fast policy (issue #910 follow-up).** Reference data is regulated
evidence — a silently-degraded DoC that ships with only the minimal
fallback is worse than a failed export. ``load_harmonised_standards``
raises :class:`ReferenceDataError` when the JSON is missing or corrupt
so the operator sees the install-time bug immediately instead of
discovering it months later in the bundle. Callers that explicitly
want graceful degradation (e.g. embedding a copy of the reference
data in the export ZIP when the file is unreadable) call
``read_harmonised_standards_bytes`` which returns ``None`` rather than
raising — the export bundle then omits the embedded copy but the DoC
itself still carries the Annex V §6 list from :func:`load_harmonised_standards`.
"""

from __future__ import annotations

import copy
import functools
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

HARMONISED_STANDARDS_PATH: Path = (
    Path(__file__).resolve().parent.parent / "reference_data" / "cra-harmonised-standards.json"
)


class ReferenceDataError(RuntimeError):
    """Raised when shipped reference data is missing or corrupt.

    Install-time bug; surfaces loudly so a broken deploy can't quietly
    ship DoCs that omit harmonised-standard citations.
    """


def read_harmonised_standards_bytes() -> bytes | None:
    """Return the raw JSON bytes, or None if the file is missing / unreadable.

    Used by the export service to embed a verbatim copy of the reference
    data in the bundle. Returning ``None`` signals "skip the embedded
    copy"; the DoC section is rendered by :func:`load_harmonised_standards`
    which fails loudly if the same file is unreadable.
    """
    try:
        return HARMONISED_STANDARDS_PATH.read_bytes()
    except OSError:
        logger.exception("cra-harmonised-standards.json missing from installed app")
        return None


@functools.cache
def _load_cached() -> dict[str, Any]:
    try:
        raw = HARMONISED_STANDARDS_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReferenceDataError(
            f"cra-harmonised-standards.json is missing or unreadable at {HARMONISED_STANDARDS_PATH}"
        ) from exc
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReferenceDataError(
            f"cra-harmonised-standards.json at {HARMONISED_STANDARDS_PATH} is not valid JSON"
        ) from exc
    # Valid JSON is not enough — the loader contract is "returns a
    # dict with a ``standards`` list". Parsing ``[...]`` or ``"foo"``
    # would pass ``json.loads`` but blow up later at ``.get("standards")``
    # with an opaque AttributeError. Surface the shape mismatch as the
    # same :class:`ReferenceDataError` so operators see one error.
    if not isinstance(data, dict) or not isinstance(data.get("standards"), list):
        raise ReferenceDataError(
            f"cra-harmonised-standards.json at {HARMONISED_STANDARDS_PATH} "
            "must be a JSON object with a top-level 'standards' list"
        )
    return data


def load_harmonised_standards() -> dict[str, Any]:
    """Load + cache the reference data.

    Raises :class:`ReferenceDataError` if the shipped JSON is missing or
    corrupt — regulated-evidence exports must not silently ship with a
    degraded standards list.

    The returned dict is a deep copy of the cached payload so callers
    that mutate their view (e.g. tests that splice fixture data) don't
    poison the shared cache.
    """
    return copy.deepcopy(_load_cached())

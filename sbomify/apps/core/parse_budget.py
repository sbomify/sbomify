"""How much memory a JSON document takes once parsed, read from its bytes alone.

Kept apart from the MCP limits that use it so that a caller outside MCP, such as
the fix prompt reading a stored SBOM, can bound a parse without loading the MCP
SDK, whose models pydantic builds at import time.
"""

from __future__ import annotations

PARSE_MEMORY_FACTOR = 8
"""How many times the byte ceiling a document may take once parsed.

Real SBOMs take two to four times their size as Python objects, so one at the
ceiling fits. A document built of tiny objects takes up to thirty times, and
that is what this refuses."""


def parsed_size_estimate(raw: bytes) -> int:
    """An upper bound on what ``json.loads(raw)`` holds in memory, read from the text alone.

    Each object or array costs up to about 256 bytes once parsed, each further
    member about 64, and text about twice its length. Measured against the SBOM
    fixtures and against arrays of empty objects, arrays, zeros and strings,
    every one came in under it. A brace or comma inside a string only makes it
    higher. Three byte counts, so a document is sized without being parsed.
    """
    containers = raw.count(b"{") + raw.count(b"[")
    return 2 * len(raw) + 256 * containers + 64 * raw.count(b",")


def within_parse_budget(raw: bytes, ceiling: int) -> bool:
    """Whether ``raw`` is under ``ceiling`` bytes and parses into no more than ``PARSE_MEMORY_FACTOR`` times it."""
    return len(raw) <= ceiling and parsed_size_estimate(raw) <= PARSE_MEMORY_FACTOR * ceiling

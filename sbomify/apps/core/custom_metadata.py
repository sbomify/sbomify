"""Free-form key/value metadata for products and components.

A workspace often needs to hang its own facts off a product or component:
an internal cost centre, a team owner, a ticket queue, a deployment tier.
None of these deserve a column, and none are part of an SBOM standard, so
they live in one ``custom_metadata`` JSON object of string keys to string
values.

The shape is deliberately flat and string-only. Nested values or numbers
would make the API a schemaless document store, and every consumer (the
UI, exports, the API) would have to guess at types. Strings in, strings out.

This module holds the one validation rule every write path shares, the API
schemas and the HTMX views alike, so the limits cannot drift between them.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import AfterValidator, BeforeValidator

MAX_PAIRS = 50
MAX_KEY_LENGTH = 128
MAX_VALUE_LENGTH = 1024


class CustomMetadataError(ValueError):
    """Raised when a custom metadata payload breaks one of the rules."""


def normalize_custom_metadata(raw: Any) -> dict[str, str]:
    """Validate and normalise a custom metadata mapping.

    Keys are stripped and must be non-empty and unique after stripping, so
    ``"team"`` and ``" team "`` cannot both be stored. Values are stripped
    too; an empty value is allowed, since "known to be blank" is a fact.
    The result is sorted by key: the column is Postgres ``jsonb``, which does
    not keep insertion order, so alphabetical is the only stable order.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CustomMetadataError("Custom metadata must be an object of string keys to string values")
    if len(raw) > MAX_PAIRS:
        raise CustomMetadataError(f"Custom metadata may hold at most {MAX_PAIRS} entries")

    result: dict[str, str] = {}
    for raw_key, raw_value in raw.items():
        if not isinstance(raw_key, str):
            raise CustomMetadataError("Custom metadata keys must be strings")
        if not isinstance(raw_value, str):
            raise CustomMetadataError(f"Value for '{raw_key}' must be a string")
        key = raw_key.strip()
        value = raw_value.strip()
        if "\u0000" in key or "\u0000" in value:
            raise CustomMetadataError("Custom metadata keys and values must not contain null characters")
        if not key:
            raise CustomMetadataError("Custom metadata keys must not be empty")
        if len(key) > MAX_KEY_LENGTH:
            raise CustomMetadataError(f"Key '{key[:32]}…' is longer than {MAX_KEY_LENGTH} characters")
        if len(value) > MAX_VALUE_LENGTH:
            raise CustomMetadataError(f"Value for '{key}' is longer than {MAX_VALUE_LENGTH} characters")
        if key in result:
            raise CustomMetadataError(f"Duplicate key '{key}'")
        result[key] = value
    return dict(sorted(result.items()))


def custom_metadata_from_pairs(keys: list[str], values: list[str]) -> dict[str, str]:
    """Build a mapping from parallel form lists, dropping fully blank rows.

    HTML forms post repeated ``key``/``value`` fields; a row the user added
    and left empty is not an error, it is nothing.
    """
    if len(keys) != len(values):
        raise CustomMetadataError("Mismatched keys and values")
    raw: dict[str, str] = {}
    for key, value in zip(keys, values):
        if not key.strip() and not value.strip():
            continue
        if not key.strip():
            raise CustomMetadataError("Every value needs a key")
        if key.strip() in raw:
            raise CustomMetadataError(f"Duplicate key '{key.strip()}'")
        raw[key.strip()] = value
    return normalize_custom_metadata(raw)


def _reject_non_dict(value: Any) -> Any:
    # Pydantic would coerce some inputs on its own; give one clear message instead.
    if value is not None and not isinstance(value, dict):
        raise CustomMetadataError("Custom metadata must be an object of string keys to string values")
    return value


def _validate(value: dict[str, str]) -> dict[str, str]:
    return normalize_custom_metadata(value)


CustomMetadata = Annotated[dict[str, str], BeforeValidator(_reject_non_dict), AfterValidator(_validate)]
"""Pydantic type for API schemas carrying custom metadata."""

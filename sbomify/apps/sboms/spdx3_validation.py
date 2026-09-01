"""Strict validation of SPDX 3.0.1+ documents against the vendored schema.

The official 259 KB ``spdx_3.0.1-schema.json`` ships in this repo; this module
is its only runtime consumer. The compiled validator is cached at module
level — the schema declares Draft 2020-12 and compiling it per upload is
measurable.

Only documents that claim 3.0.1 or later are held to it: 3.0.0 producers
(syft, sbom-tool, JFrog) predate the schema and there is no vendored 3.0.0
schema to hold them to, and legacy ``spdxVersion``/``elements`` documents
declare themselves non-conformant by shape. A formatting-only 3.0.x patch
above 3.0.1 validates cleanly — the schema's ``specVersion`` is a semver
pattern, not a pinned constant.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "spdx_3.0.1-schema.json"


@cache
def _validator() -> Any:
    from jsonschema import Draft202012Validator

    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


def spdx3_schema_errors(document: dict[str, Any], limit: int = 3) -> list[str]:
    """The first ``limit`` schema violations as ``pointer: message`` strings.

    The full error list on a large document can run to thousands of entries;
    the first few name the offending property paths, which is what an API
    error response can usefully carry.
    """
    errors: list[str] = []
    for error in _validator().iter_errors(document):
        # Pointer-shaped location labels for a human reader: tokens are
        # RFC 6901-escaped so a / or ~ in a property name stays one token,
        # and the document root reads as words rather than an empty string.
        path_parts = [str(part).replace("~", "~0").replace("/", "~1") for part in error.absolute_path]
        pointer = "/" + "/".join(path_parts) if path_parts else "(document root)"
        errors.append(f"{pointer}: {error.message[:200]}")
        if len(errors) >= limit:
            break
    return errors

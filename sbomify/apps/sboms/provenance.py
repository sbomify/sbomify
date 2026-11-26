"""Read in-toto provenance in the shapes build tools actually write.

The upload endpoint and the verification plugin both need the Statement out
of whatever was posted, so the parsing lives here once. Accepted, alone or one
per line of a ``.intoto.jsonl`` file:

- an in-toto Statement (``_type`` + ``subject``)
- a DSSE envelope (``payloadType`` + base64 ``payload``), as written by
  slsa-github-generator
- a Sigstore bundle carrying a ``dsseEnvelope``, as written by
  ``cosign attest-blob --bundle`` and GitHub's artifact attestations

Signatures on the envelope are not checked here. This only extracts the
statements so their subjects can be compared with the SBOM digest.
"""

from __future__ import annotations

import base64
import json
from typing import Any


class ProvenanceFormatError(ValueError):
    """The body is not a provenance document this module understands."""


def _statement_from_document(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict):
        raise ProvenanceFormatError("Provenance must be a JSON object")

    if "_type" in doc and "subject" in doc:
        return doc

    nested = doc.get("dsseEnvelope")
    envelope: dict[str, Any] = nested if isinstance(nested, dict) else doc
    if "payloadType" in envelope and "payload" in envelope:
        try:
            statement = json.loads(base64.b64decode(envelope["payload"], validate=True))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
            raise ProvenanceFormatError("Failed to decode DSSE envelope payload") from exc
        if not isinstance(statement, dict):
            raise ProvenanceFormatError("DSSE payload is not a JSON object")
        return statement

    raise ProvenanceFormatError(
        "Provenance must be a DSSE envelope (with payloadType/payload), a Sigstore bundle with a "
        "dsseEnvelope, or a direct Statement (with subject)"
    )


def parse_statements(raw: bytes | str) -> list[dict[str, Any]]:
    """Return every in-toto Statement in ``raw``.

    A single JSON document is tried first, so a pretty-printed envelope keeps
    working. Otherwise each non-blank line is read as its own document.
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProvenanceFormatError("Invalid JSON") from exc

    try:
        return [_statement_from_document(json.loads(raw))]
    except json.JSONDecodeError:
        pass

    lines = [line for line in raw.splitlines() if line.strip()]
    if len(lines) < 2:
        raise ProvenanceFormatError("Invalid JSON")
    statements = []
    for number, line in enumerate(lines, start=1):
        try:
            doc = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProvenanceFormatError(f"Invalid JSON on line {number}") from exc
        statements.append(_statement_from_document(doc))
    return statements


def subject_digests(statements: list[dict[str, Any]]) -> list[str]:
    """Every subject SHA-256 named by ``statements``, in order."""
    digests = []
    for statement in statements:
        subjects = statement.get("subject")
        if not isinstance(subjects, list):
            continue
        for subject in subjects:
            digest = subject.get("digest") if isinstance(subject, dict) else None
            if isinstance(digest, dict) and isinstance(digest.get("sha256"), str):
                digests.append(digest["sha256"])
    return digests


def matching_subject(statements: list[dict[str, Any]], sha256: str) -> dict[str, Any] | None:
    """The first subject whose SHA-256 is ``sha256``, or ``None``."""
    for statement in statements:
        subjects = statement.get("subject")
        if not isinstance(subjects, list):
            continue
        for subject in subjects:
            digest = subject.get("digest") if isinstance(subject, dict) else None
            if isinstance(digest, dict) and digest.get("sha256") == sha256:
                return dict(subject)
    return None

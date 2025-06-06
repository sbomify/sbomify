from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from license_expression import LicenseSymbolTableError, Licensing

SPDX_SYMBOLS: Dict[str, dict] = {}
CUSTOM_SYMBOLS: Dict[str, dict] = {}
ALL_LICENSES: Dict[str, dict] = {}

_licensing = Licensing()


def _simple_yaml_load(text: str) -> Dict[str, Dict[str, str]]:
    data: Dict[str, Dict[str, str]] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if not line.startswith(" ") and line.endswith(":"):
            current_key = line[:-1]
            data[current_key] = {}
        elif current_key and ":" in line:
            k, v = line.split(":", 1)
            data[current_key][k.strip()] = v.strip()
    return data


def _load_spdx() -> None:
    global SPDX_SYMBOLS
    SPDX_SYMBOLS = {}
    for key, sym in _licensing.symbols.items():
        SPDX_SYMBOLS[key] = {
            "key": key,
            "name": sym.name,
            "category": sym.category,
            "origin": "SPDX",
        }


def _load_custom() -> None:
    global CUSTOM_SYMBOLS
    path = Path(__file__).resolve().parent / "data" / "non_spdx.yaml"
    with open(path, "r", encoding="utf-8") as fh:
        content = fh.read()
    parsed = _simple_yaml_load(content)
    CUSTOM_SYMBOLS = {k: {"key": k, **v, "origin": v.get("origin", "Custom")} for k, v in parsed.items()}


def load_licenses() -> None:
    _load_spdx()
    _load_custom()
    global ALL_LICENSES
    ALL_LICENSES = {**SPDX_SYMBOLS, **CUSTOM_SYMBOLS}


def category_counts(tokens: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for tok in tokens:
        entry = ALL_LICENSES.get(tok)
        cat = entry.get("category") if entry else "Unknown"
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def validate_expression(expr: str) -> tuple[int, dict]:
    try:
        tree = _licensing.parse(expr, validate=True)
    except LicenseSymbolTableError as exc:  # Syntax error
        return 400, {"error": str(exc)}

    tokens = [sym.key for sym in tree.symbols]
    unknown = [t for t in tokens if t not in ALL_LICENSES]

    return 200, {
        "normalized": str(tree),
        "tokens": [{"key": t, "known": t not in unknown} for t in tokens],
        "unknown_tokens": unknown,
        "category_summary": category_counts(tokens),
    }

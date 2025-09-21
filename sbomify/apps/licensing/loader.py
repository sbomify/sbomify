"""License loader module for handling SPDX and custom licenses."""

import os
from typing import Any, Dict

import yaml
from license_expression import get_spdx_licensing

# Initialize the licensing parser
licensing = get_spdx_licensing()

# Load SPDX licenses
SPDX_SYMBOLS = licensing.known_symbols


# Load custom non-SPDX licenses
def load_custom_licenses() -> Dict[str, Any]:
    """Load custom non-SPDX licenses from YAML file."""
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    yaml_path = os.path.join(data_dir, "non_spdx.yaml")

    with open(yaml_path, "r") as f:
        return yaml.safe_load(f)


CUSTOM_SYMBOLS = load_custom_licenses()

# Combine all licenses
ALL_LICENSES = {**SPDX_SYMBOLS, **CUSTOM_SYMBOLS}


def get_license_list() -> list:
    """Get a list of all available licenses with their metadata."""
    licenses = []

    # Add SPDX licenses (without category since we can't determine it reliably)
    for key, symbol in SPDX_SYMBOLS.items():
        licenses.append(
            {
                "key": key,
                "name": str(symbol),
                "origin": "SPDX",
                "url": getattr(symbol, "url", None),
            }
        )

    # Add custom licenses (with category since it's explicitly defined)
    for key, data in CUSTOM_SYMBOLS.items():
        licenses.append(
            {
                "key": key,
                "name": data["name"],
                "category": data["category"],
                "origin": data["origin"],
                "url": data["url"],
            }
        )

    return sorted(licenses, key=lambda x: x["key"])


def validate_expression(expr: str) -> dict:
    """Validate a license expression and return detailed information."""
    from license_expression import ExpressionError

    try:
        tree = licensing.parse(expr, validate=False)
    except ExpressionError:
        return {"status": 400, "error": "Processing error"}
    except Exception:
        return {"status": 400, "error": "Invalid expression"}

    # Get tokens from the parsed tree - these are the individual license identifiers
    tokens = []
    for symbol in tree.symbols:
        if hasattr(symbol, "key"):
            # Simple license symbol
            tokens.append(symbol.key)
        elif hasattr(symbol, "license_symbol") and hasattr(symbol, "exception_symbol"):
            # License with exception symbol - extract both parts
            tokens.append(symbol.license_symbol.key)
            tokens.append(symbol.exception_symbol.key)
        else:
            tokens.append(str(symbol))

    # Remove duplicates while preserving order
    unique_tokens = list(dict.fromkeys(tokens))
    unknown = [t for t in unique_tokens if t not in ALL_LICENSES]

    return {
        "status": 200,
        "normalized": str(tree),
        "tokens": [{"key": t, "known": t not in unknown} for t in unique_tokens],
        "unknown_tokens": unknown,
    }

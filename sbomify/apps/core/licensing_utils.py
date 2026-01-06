"""
Shared licensing utility functions.
Moved here to avoid circular imports between licensing and other apps.
"""

import re

from license_expression import ExpressionError, get_spdx_licensing

# Initialize the licensing parser
_licensing = get_spdx_licensing()


def is_license_expression(license_string: str) -> bool:
    """Check if a string is a license expression (contains operators).

    Uses the license_expression library to parse and detect if the string
    is an expression (contains operators like AND, OR, WITH) vs a simple
    license identifier. This matches the frontend implementation which also
    uses the license-expressions library.

    Args:
        license_string: The license string to check

    Returns:
        True if the string is a license expression, False if it's a simple
        license ID or invalid
    """
    if not license_string or not isinstance(license_string, str):
        return False

    try:
        # Try to parse the expression using the license_expression library
        tree = _licensing.parse(license_string, validate=False)

        # A simple license ID (e.g., "MIT") will parse successfully but
        # will have only 1 symbol. An expression (e.g., "MIT OR Apache-2.0")
        # will have multiple symbols. Check if there are multiple symbols
        # (indicating an expression with operators)
        symbol_count = len(list(tree.symbols))
        if symbol_count > 1:
            return True

        # For single symbol cases, check if it's a WITH expression or contains
        # operators. "Apache-2.0 WITH Commons-Clause" parses as a single symbol
        # (LicenseWithExceptionSymbol), so check the tree type or string for operators
        tree_type_name = type(tree).__name__
        if "WithException" in tree_type_name:
            return True

        # Check if the original string contains operators (AND, OR, WITH)
        operator_pattern = r"(?:^|\s|\(|\))(AND|OR|WITH)(?:\s|\(|\)|$)"
        if re.search(operator_pattern, license_string, re.IGNORECASE):
            return True

        # Single symbol, no operators - it's a simple license ID
        return False

    except ExpressionError:
        # Failed to parse - not a valid expression or license ID
        return False
    except Exception:
        # Other parsing errors - treat as not an expression
        return False

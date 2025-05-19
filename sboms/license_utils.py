"""
License expression handling utilities.

This module provides utilities for parsing, validating, and normalizing license expressions
using the license-expression library.
"""

from typing import List, Tuple

from license_expression import LicenseExpression as LELicenseExpression
from license_expression import get_spdx_licensing

EXTRA_LICENSES = {
    "Commons-Clause": {
        "name": "Commons Clause",
        "is_osi_approved": False,
        "is_fsf_approved": False,
        "is_spdx": False,
        "is_recognized": True,
        "is_deprecated": False,
        "url": "https://commonsclause.com/",
    },
    "BUSL-1.1": {
        "name": "Business Source License 1.1",
        "is_osi_approved": False,
        "is_fsf_approved": False,
        "is_spdx": False,
        "is_recognized": True,
        "is_deprecated": False,
        "url": "https://spdx.org/licenses/BUSL-1.1.html",
    },
    "SSPL-1.0": {
        "name": "Server Side Public License v1",
        "is_osi_approved": False,
        "is_fsf_approved": False,
        "is_spdx": False,
        "is_recognized": True,
        "is_deprecated": False,
        "url": "https://www.mongodb.com/licensing/server-side-public-license",
    },
    "ELv2": {
        "name": "Elastic License 2.0",
        "is_osi_approved": False,
        "is_fsf_approved": False,
        "is_spdx": False,
        "is_recognized": True,
        "is_deprecated": False,
        "url": "https://www.elastic.co/licensing/elastic-license",
    },
    "CCL": {
        "name": "Confluent Community License",
        "is_osi_approved": False,
        "is_fsf_approved": False,
        "is_spdx": False,
        "is_recognized": True,
        "is_deprecated": False,
        "url": "https://www.confluent.io/software-licensing-policy/",
    },
    "RSAL": {
        "name": "Redis Source Available License v2",
        "is_osi_approved": False,
        "is_fsf_approved": False,
        "is_spdx": False,
        "is_recognized": True,
        "is_deprecated": False,
        "url": "https://redis.com/legal/rsalv2-agreement/",
    },
    "FSL": {
        "name": "Functional Source License",
        "is_osi_approved": False,
        "is_fsf_approved": False,
        "is_spdx": False,
        "is_recognized": True,
        "is_deprecated": False,
        "url": "https://functionalsource.org/",
    },
    "Polyform": {
        "name": "Polyform License (Noncommercial, Small-Business, Strict, etc.)",
        "is_osi_approved": False,
        "is_fsf_approved": False,
        "is_spdx": False,
        "is_recognized": True,
        "is_deprecated": False,
        "url": "https://polyformproject.org/",
    },
    "Fair-Source-1.0": {
        "name": "Fair Source License (original Fair Source 1.0)",
        "is_osi_approved": False,
        "is_fsf_approved": False,
        "is_spdx": False,
        "is_recognized": True,
        "is_deprecated": False,
        "url": "https://fair.io/",
    },
    "Prosperity": {
        "name": "Prosperity Public License",
        "is_osi_approved": False,
        "is_fsf_approved": False,
        "is_spdx": False,
        "is_recognized": True,
        "is_deprecated": False,
        "url": "https://prosperitylicense.com/",
    },
    "TSL": {
        "name": "Timescale License",
        "is_osi_approved": False,
        "is_fsf_approved": False,
        "is_spdx": False,
        "is_recognized": True,
        "is_deprecated": False,
        "url": "https://docs.timescale.com/licenses/tsl/",
    },
}


class LicenseExpressionHandler:
    """Handles parsing, validation, and normalization of license expressions."""

    def __init__(self):
        self.spdx_licensing = get_spdx_licensing()
        # Always include extra licenses in known symbols
        for extra in EXTRA_LICENSES:
            ks = self.spdx_licensing.known_symbols
            if isinstance(ks, dict):
                ks[extra] = True
            elif hasattr(ks, "add"):
                ks.add(extra)
            elif isinstance(ks, list):
                if extra not in ks:
                    ks.append(extra)

    def parse_expression(self, expression: str) -> LELicenseExpression:
        """
        Parse a license expression string into a structured expression.

        Args:
            expression: The license expression string to parse

        Returns:
            A parsed license expression object

        Raises:
            ValueError: If the expression is invalid
        """
        return self.spdx_licensing.parse(expression)

    def normalize_expression(self, expression: str) -> str:
        """
        Normalize a license expression to its canonical form.

        Args:
            expression: The license expression string to normalize

        Returns:
            The normalized license expression string

        Raises:
            ValueError: If the expression is invalid
        """
        parsed = self.parse_expression(expression)
        return str(parsed)

    def validate_expression(self, expression: str) -> Tuple[bool, List[str]]:
        """
        Validate a license expression and return any warnings.

        Args:
            expression: The license expression string to validate

        Returns:
            A tuple of (is_valid, list_of_warnings)
        """
        try:
            parsed = self.parse_expression(expression)
            symbols = list(getattr(parsed, "symbols", []))
            unknown = []
            warnings = []
            for symbol in symbols:
                s = str(symbol)
                if not (
                    s in self.spdx_licensing.known_symbols
                    or s.replace("-exception-", "-") in self.spdx_licensing.known_symbols
                    or s in EXTRA_LICENSES
                ):
                    unknown.append(s)
                if s == "Commons-Clause":
                    warnings.append(
                        "Warning: Commons-Clause is not OSI or FSF approved and is not considered open source."
                    )
            if unknown:
                warnings.append(f"Warning: Unknown license(s) or exception(s): {', '.join(unknown)}")
            return True, warnings
        except Exception as e:
            import re

            symbols = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-\.\+]*", expression)
            unknown = []
            warnings = []
            for s in symbols:
                if s in {"AND", "OR", "WITH"}:
                    continue
                if not (
                    s in self.spdx_licensing.known_symbols
                    or s.replace("-exception-", "-") in self.spdx_licensing.known_symbols
                    or s in EXTRA_LICENSES
                ):
                    unknown.append(s)
                if s == "Commons-Clause":
                    warnings.append(
                        "Warning: Commons-Clause is not OSI or FSF approved and is not considered open source."
                    )
            if not unknown:
                # All symbols are recognized, treat as valid
                return True, warnings
            return False, [str(e)]

    def is_spdx_identifier(self, identifier: str) -> bool:
        """
        Check if an identifier is a valid SPDX license or exception.

        Args:
            identifier: The license or exception identifier to check

        Returns:
            True if the identifier is a valid SPDX license or exception, False otherwise
        """
        # First check if it's a known symbol
        if (
            identifier in self.spdx_licensing.known_symbols
            or identifier.replace("-exception-", "-") in self.spdx_licensing.known_symbols
        ):
            return True

        # Then check if it's a deprecated identifier
        DEPRECATED_IDS = {
            "GPL-2.0",
            "GPL-2.0+",
            "GPL-3.0",
            "GPL-3.0+",
            "LGPL-2.0",
            "LGPL-2.0+",
            "LGPL-2.1",
            "LGPL-2.1+",
            "LGPL-3.0",
            "LGPL-3.0+",
            "AGPL-1.0",
            "AGPL-3.0",
            "GFDL-1.1",
            "GFDL-1.2",
            "GFDL-1.3",
        }
        return identifier in DEPRECATED_IDS

    def is_deprecated_spdx_identifier(self, identifier: str) -> bool:
        """
        Check if an identifier is a deprecated SPDX license or exception.
        Uses a hardcoded set based on the SPDX License List.
        """
        DEPRECATED_IDS = {
            "GPL-2.0",
            "GPL-2.0+",
            "GPL-3.0",
            "GPL-3.0+",
            "LGPL-2.0",
            "LGPL-2.0+",
            "LGPL-2.1",
            "LGPL-2.1+",
            "LGPL-3.0",
            "LGPL-3.0+",
            "AGPL-1.0",
            "AGPL-3.0",
            "GFDL-1.1",
            "GFDL-1.2",
            "GFDL-1.3",
            # Add more as needed from SPDX list
        }
        return identifier in DEPRECATED_IDS

    def compare_expressions(self, expr1: str, expr2: str) -> bool:
        """
        Compare two license expressions for equivalence.

        Args:
            expr1: First license expression
            expr2: Second license expression

        Returns:
            True if the expressions are equivalent, False otherwise
        """
        try:
            parsed1 = self.parse_expression(expr1)
            parsed2 = self.parse_expression(expr2)
            return str(parsed1) == str(parsed2)
        except Exception:
            return False

    def get_expression_type(self, expression: str) -> str:
        """
        Determine the type of license expression.

        Args:
            expression: The license expression to analyze

        Returns:
            One of: 'simple', 'compound', 'with_exception'
        """
        try:
            parsed = self.parse_expression(expression)
            expr_str = str(parsed)
            if "WITH" in expr_str:
                return "with_exception"
            elif "AND" in expr_str or "OR" in expr_str:
                return "compound"
            else:
                return "simple"
        except Exception:
            return "simple"  # Default to simple if parsing fails

    def get_operator(self, expression: str) -> str | None:
        """
        Extract the operator from a license expression.

        Args:
            expression: The license expression to analyze

        Returns:
            The operator ('AND', 'OR', 'WITH') or None if no operator
        """
        try:
            parsed = self.parse_expression(expression)
            expr_str = str(parsed)
            if "WITH" in expr_str:
                return "WITH"
            elif "AND" in expr_str:
                return "AND"
            elif "OR" in expr_str:
                return "OR"
            return None
        except Exception:
            return None

    def extract_operands(self, expression: str) -> dict:
        """
        Extract operands from a license expression.
        For AND/OR: returns {'children': [str, ...]}
        For WITH: returns {'license': str, 'exception': str}
        For simple: returns {}
        """
        parsed = self.parse_expression(expression)
        # AND/OR: n-ary, use .args
        if hasattr(parsed, "operator") and str(parsed.operator).strip() in ("AND", "OR"):
            return {"children": [str(arg) for arg in getattr(parsed, "args", ())]}
        # WITH: use license_symbol and exception_symbol
        if hasattr(parsed, "license_symbol") and hasattr(parsed, "exception_symbol"):
            return {
                "license": str(parsed.license_symbol),
                "exception": str(parsed.exception_symbol),
            }
        # Simple
        return {}

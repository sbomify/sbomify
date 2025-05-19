"""
License service for managing license expressions and components.

This module provides services for managing license expressions and components,
including creation, validation, and normalization of license expressions.
"""

from typing import List, Optional, Tuple

from django.db import transaction

from .license_utils import LicenseExpressionHandler
from .models import LicenseComponent, LicenseExpression


class LicenseService:
    """Service for managing license expressions and components."""

    def __init__(self):
        self.expression_handler = LicenseExpressionHandler()

    def create_license_component(
        self,
        identifier: str,
        name: str,
        type: str = "spdx",
        is_deprecated: bool = False,
        is_osi_approved: bool = False,
        is_fsf_approved: bool = False,
        url: Optional[str] = None,
        text: Optional[str] = None,
    ) -> LicenseComponent:
        """
        Create a new license component.

        Args:
            identifier: The SPDX identifier for the license
            name: Human readable name of the license
            type: Type of license (spdx, custom)
            is_deprecated: Whether the license is deprecated
            is_osi_approved: Whether the license is OSI approved
            is_fsf_approved: Whether the license is FSF approved
            url: URL to the license text
            text: The license text content

        Returns:
            The created LicenseComponent instance
        """
        return LicenseComponent.objects.create(
            identifier=identifier,
            name=name,
            type=type,
            is_deprecated=is_deprecated,
            is_osi_approved=is_osi_approved,
            is_fsf_approved=is_fsf_approved,
            url=url,
            text=text,
        )

    def create_license_expression(
        self,
        expression: str,
        source: str = "spdx",
        validate: bool = True,
    ) -> Tuple[Optional[LicenseExpression], List[str]]:
        """
        Create a new license expression as a tree structure.

        Args:
            expression: The license expression string
            source: Source of the expression (spdx, cyclonedx, etc.)
            validate: Whether to validate the expression before creating

        Returns:
            A tuple of (LicenseExpression instance, list of validation errors)
        """
        if validate:
            is_valid, errors = self.expression_handler.validate_expression(expression)
            if not is_valid:
                # Still create the expression, but mark as invalid
                pass
        else:
            errors = []

        def _create_node(expr_str: str, parent=None, order=0) -> LicenseExpression:
            node_type = self.expression_handler.get_expression_type(expr_str)
            node_operator = self.expression_handler.get_operator(expr_str)
            normalized_node = self.expression_handler.normalize_expression(expr_str)
            # If simple, create a leaf node
            if node_type == "simple":
                component, _ = LicenseComponent.objects.get_or_create(
                    identifier=normalized_node,
                    defaults={
                        "name": normalized_node,
                        "type": "spdx",
                    },
                )
                return LicenseExpression.objects.create(
                    parent=parent,
                    order=order,
                    operator=None,
                    component=component,
                    expression=expr_str,
                    normalized_expression=normalized_node,
                    source=source,
                    validation_status="valid" if not errors else "warning",
                    validation_errors=errors,
                )
            # For AND/OR and WITH, create an operator node and children
            node = LicenseExpression.objects.create(
                parent=parent,
                order=order,
                operator=node_operator,
                component=None,
                expression=expr_str,
                normalized_expression=normalized_node,
                source=source,
                validation_status="valid" if not errors else "warning",
                validation_errors=errors,
            )
            operands = self.expression_handler.extract_operands(expr_str)
            if "children" in operands:
                for idx, child_expr in enumerate(operands["children"]):
                    _create_node(child_expr, parent=node, order=idx)
            elif "license" in operands and "exception" in operands:
                _create_node(operands["license"], parent=node, order=0)
                _create_node(operands["exception"], parent=node, order=1)
            return node

        with transaction.atomic():
            root = _create_node(expression)
        return root, errors

    def get_or_create_license_expression(self, expression: str, source: str = "spdx") -> Tuple[LicenseExpression, bool]:
        """
        Get an existing license expression or create a new one.

        Args:
            expression: The license expression string
            source: Source of the expression

        Returns:
            A tuple of (LicenseExpression instance, created flag)
        """
        try:
            return (
                LicenseExpression.objects.get(normalized_expression=expression),
                False,
            )
        except LicenseExpression.DoesNotExist:
            expr, errors = self.create_license_expression(expression, source)
            return expr, True

    def validate_license_expression(self, expression: str) -> Tuple[bool, List[str]]:
        """
        Validate a license expression.

        Args:
            expression: The license expression to validate

        Returns:
            A tuple of (is_valid, list_of_errors)
        """
        return self.expression_handler.validate_expression(expression)

    def normalize_license_expression(self, expression: str) -> str:
        """
        Normalize a license expression to its canonical form.

        Args:
            expression: The license expression to normalize

        Returns:
            The normalized license expression string
        """
        return self.expression_handler.normalize_expression(expression)

    def compare_license_expressions(self, expr1: str, expr2: str) -> bool:
        """
        Compare two license expressions for equivalence.
        Note: This is a string comparison and does not canonicalize order for OR/AND.
        """
        return self.expression_handler.compare_expressions(expr1, expr2)

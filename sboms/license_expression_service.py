from typing import List, Tuple

from django.db import transaction
from license_expression import LicenseWithExceptionSymbol

from sboms.license_utils import EXTRA_LICENSES, LicenseExpressionHandler
from sboms.models import LicenseComponent, LicenseExpression


class LicenseExpressionService:
    """
    Service for parsing, validating, normalizing, and creating LicenseExpression trees from SPDX strings.
    """

    def __init__(self):
        self.handler = LicenseExpressionHandler()

    def get_or_create_license_component(self, identifier: str) -> LicenseComponent:
        # Check if identifier is a known extra license
        if identifier in EXTRA_LICENSES:
            meta = EXTRA_LICENSES[identifier]
            component, created = LicenseComponent.objects.get_or_create(
                identifier=identifier,
                defaults={
                    "name": meta["name"],
                    "type": "custom",
                    "is_spdx": meta["is_spdx"],
                    "is_recognized": meta["is_recognized"],
                    "is_deprecated": meta["is_deprecated"],
                    "is_osi_approved": meta["is_osi_approved"],
                    "is_fsf_approved": meta["is_fsf_approved"],
                    "url": meta.get("url"),
                },
            )
            return component
        # Check if identifier is a valid SPDX license or exception
        is_spdx = self.handler.is_spdx_identifier(identifier)
        is_deprecated = self.handler.is_deprecated_spdx_identifier(identifier) if is_spdx else False
        is_recognized = is_spdx  # Extend this if you want to support custom known licenses
        component, created = LicenseComponent.objects.get_or_create(
            identifier=identifier,
            defaults={
                "name": identifier,
                "type": "spdx" if is_spdx else "custom",
                "is_spdx": is_spdx,
                "is_recognized": is_recognized,
                "is_deprecated": is_deprecated,
            },
        )
        # If the component already exists but the flags are not set, update them
        if not created and (
            component.is_spdx != is_spdx
            or component.is_recognized != is_recognized
            or component.is_deprecated != is_deprecated
        ):
            component.is_spdx = is_spdx
            component.is_recognized = is_recognized
            component.is_deprecated = is_deprecated
            component.save(update_fields=["is_spdx", "is_recognized", "is_deprecated"])
        return component

    def validate_license_expression(self, expression: str) -> Tuple[bool, List[str]]:
        return self.handler.validate_expression(expression)

    def normalize_license_expression(self, expression: str) -> str:
        return self.handler.normalize_expression(expression)

    @transaction.atomic
    def create_license_expression_tree(self, expression: str, source: str = "spdx") -> LicenseExpression:
        """
        Parse and create a LicenseExpression tree from an SPDX string.
        Returns the root LicenseExpression node.
        """
        parsed = self.handler.parse_expression(expression)
        is_valid, warnings = self.handler.validate_expression(expression)
        validation_status = "warning" if warnings else "valid" if is_valid else "invalid"

        def _create_node(parsed_node, parent=None, order=0) -> LicenseExpression:
            # WITH nodes must be treated as operator nodes
            if isinstance(parsed_node, LicenseWithExceptionSymbol):
                operator = "WITH"
                node = LicenseExpression.objects.create(
                    parent=parent,
                    order=order,
                    operator=operator,
                    component=None,
                    expression=str(parsed_node),
                    normalized_expression=str(parsed_node),
                    source=source,
                    validation_status=validation_status,
                    validation_errors=warnings,
                )
                # SPDX: left WITH exception
                left_component = self.get_or_create_license_component(str(parsed_node.license_symbol))
                if not left_component.is_spdx:
                    node.validation_errors.append(
                        f"Warning: License '{left_component.identifier}' is not a recognized SPDX license."
                    )
                    node.save(update_fields=["validation_errors"])
                _create_node(parsed_node.license_symbol, parent=node, order=0)
                exception_component = self.get_or_create_license_component(str(parsed_node.exception_symbol))
                if not exception_component.is_spdx:
                    node.validation_errors.append(
                        f"Warning: Exception '{exception_component.identifier}' is not a recognized SPDX exception."
                    )
                    node.save(update_fields=["validation_errors"])
                LicenseExpression.objects.create(
                    parent=node,
                    order=1,
                    component=exception_component,
                    operator=None,
                    expression=str(parsed_node.exception_symbol),
                    normalized_expression=str(parsed_node.exception_symbol),
                    source=source,
                    validation_status=validation_status,
                    validation_errors=warnings,
                )
                return node
            # If this is a leaf (license or exception)
            if not hasattr(parsed_node, "operator"):
                component = self.get_or_create_license_component(str(parsed_node))
                validation_errors_local = list(warnings)
                if not component.is_spdx:
                    validation_errors_local.append(
                        f"Warning: License '{component.identifier}' is not a recognized SPDX license."
                    )
                return LicenseExpression.objects.create(
                    parent=parent,
                    order=order,
                    component=component,
                    operator=None,
                    expression=str(parsed_node),
                    normalized_expression=str(parsed_node),
                    source=source,
                    validation_status=validation_status,
                    validation_errors=validation_errors_local,
                )
            # Otherwise, it's an operator node (AND, OR, etc.)
            op = getattr(parsed_node, "operator", None)
            operator = op.strip() if isinstance(op, str) and op else None
            node = LicenseExpression.objects.create(
                parent=parent,
                order=order,
                operator=operator,
                component=None,
                expression=str(parsed_node),
                normalized_expression=str(parsed_node),
                source=source,
                validation_status=validation_status,
                validation_errors=warnings,
            )
            # Recursively create children in order
            for idx, child in enumerate(getattr(parsed_node, "args", [])):
                _create_node(child, parent=node, order=idx)
            return node

        # Create the tree and return the root
        return _create_node(parsed, parent=None, order=0)

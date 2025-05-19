"""Tests for the license service."""

import pytest
from django.db import transaction

from ..models import LicenseComponent, LicenseExpression
from ..license_service import LicenseService


@pytest.fixture
def license_service():
    """Create a LicenseService instance."""
    return LicenseService()


@pytest.mark.django_db
class TestLicenseService:
    """Test cases for LicenseService."""

    def test_create_license_component(self, license_service):
        """Test creating a license component."""
        component = license_service.create_license_component(
            identifier="MIT",
            name="MIT License",
            is_osi_approved=True,
            url="https://opensource.org/licenses/MIT",
        )

        assert component.identifier == "MIT"
        assert component.name == "MIT License"
        assert component.type == "spdx"
        assert component.is_osi_approved is True
        assert component.is_deprecated is False
        assert component.is_fsf_approved is False
        assert component.url == "https://opensource.org/licenses/MIT"
        assert component.text is None

    def test_create_simple_license_expression(self, license_service):
        """Test creating a simple license expression."""
        expr, errors = license_service.create_license_expression("MIT")

        assert errors == []
        assert expr.expression == "MIT"
        assert expr.normalized_expression == "MIT"
        assert expr.operator is None
        assert expr.source == "spdx"
        assert expr.validation_status == "valid"
        assert expr.validation_errors == []

    def test_create_compound_license_expression(self, license_service):
        """Test creating a compound license expression."""
        expr, errors = license_service.create_license_expression("MIT OR Apache-2.0")

        assert errors == []
        assert expr.expression == "MIT OR Apache-2.0"
        assert expr.normalized_expression == "MIT OR Apache-2.0"
        assert expr.operator == "OR"
        children = list(expr.children.order_by("order"))
        assert len(children) == 2
        assert children[0].expression == "MIT"
        assert children[1].expression == "Apache-2.0"

    def test_create_expression_with_exception(self, license_service):
        """Test creating a license expression with an exception."""
        expr, errors = license_service.create_license_expression("GPL-3.0 WITH Classpath-exception-2.0")

        assert expr is not None
        assert len(errors) > 0
        assert "Warning: Unknown license(s) or exception(s): GPL-3.0-only WITH Classpath-exception-2.0" in errors[0]
        assert expr.expression == "GPL-3.0 WITH Classpath-exception-2.0"
        # The normalized form may be 'GPL-3.0-only WITH Classpath-exception-2.0'
        assert expr.normalized_expression.startswith("GPL-3.0")
        assert "WITH Classpath-exception-2.0" in expr.normalized_expression
        assert expr.operator == "WITH"
        children = list(expr.children.order_by("order"))
        assert len(children) == 2
        assert children[0].expression.startswith("GPL-3.0")
        assert children[1].expression == "Classpath-exception-2.0"

    def test_invalid_license_expression(self, license_service):
        """Test creating an invalid license expression."""
        expr, errors = license_service.create_license_expression("INVALID-LICENSE")

        assert expr is not None
        assert len(errors) > 0
        assert "Warning: Unknown license(s) or exception(s): INVALID-LICENSE" in errors[0]

    def test_get_or_create_license_expression(self, license_service):
        """Test getting or creating a license expression."""
        # First creation
        expr1, created1 = license_service.get_or_create_license_expression("MIT")
        assert created1 is True
        assert expr1.expression == "MIT"

        # Getting existing
        expr2, created2 = license_service.get_or_create_license_expression("MIT")
        assert created2 is False
        assert expr2.id == expr1.id

    def test_compare_license_expressions(self, license_service):
        """Test comparing license expressions. Note: order is not canonicalized for OR/AND."""
        # Same expressions
        assert license_service.compare_license_expressions("MIT", "MIT") is True

        # Different expressions
        assert license_service.compare_license_expressions("MIT", "Apache-2.0") is False

        # Equivalent expressions with different order (should be False)
        assert license_service.compare_license_expressions(
            "MIT OR Apache-2.0", "Apache-2.0 OR MIT"
        ) is False  # Order is not canonicalized

    def test_normalize_license_expression(self, license_service):
        """Test normalizing license expressions."""
        # Simple expression
        assert license_service.normalize_license_expression("MIT") == "MIT"

        # Compound expression
        assert license_service.normalize_license_expression(
            "MIT OR Apache-2.0"
        ) == "MIT OR Apache-2.0"

        # Expression with exception (normalized form may differ)
        norm = license_service.normalize_license_expression(
            "GPL-3.0 WITH Classpath-exception-2.0"
        )
        assert norm.startswith("GPL-3.0")
        assert "WITH Classpath-exception-2.0" in norm

    def test_validate_license_expression(self, license_service):
        """Test validating license expressions."""
        # Valid expression
        is_valid, errors = license_service.validate_license_expression("MIT")
        assert is_valid is True
        assert errors == []

        # Invalid expression (should now be valid with warnings)
        is_valid, errors = license_service.validate_license_expression("INVALID-LICENSE")
        assert is_valid is True
        assert errors
        assert "Warning: Unknown license(s) or exception(s): INVALID-LICENSE" in errors[0]
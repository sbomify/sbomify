import pytest
from django.test import TestCase
from django.db import connection
from sboms.models import LicenseExpression, LicenseComponent
from sboms.license_utils import LicenseExpressionHandler


@pytest.mark.django_db
class TestLicenseExpression(TestCase):
    def setUp(self):
        # Create some test license components
        self.mit = LicenseComponent.objects.create(
            identifier="MIT",
            name="MIT License",
            type="spdx",
            is_osi_approved=True
        )
        self.apache = LicenseComponent.objects.create(
            identifier="Apache-2.0",
            name="Apache License 2.0",
            type="spdx",
            is_osi_approved=True
        )
        self.bsd = LicenseComponent.objects.create(
            identifier="BSD-3-Clause",
            name="BSD 3-Clause License",
            type="spdx",
            is_osi_approved=True
        )
        self.gpl = LicenseComponent.objects.create(
            identifier="GPL-2.0",
            name="GNU General Public License v2.0",
            type="spdx",
            is_osi_approved=True
        )
        self.classpath = LicenseComponent.objects.create(
            identifier="Classpath-exception-2.0",
            name="Classpath Exception 2.0",
            type="spdx"
        )
        self.isc = LicenseComponent.objects.create(
            identifier="ISC",
            name="ISC License",
            type="spdx",
            is_osi_approved=True
        )

    def test_simple_license(self):
        """Test creating a simple license expression."""
        expr = LicenseExpression.objects.create(
            component=self.mit,
            expression="MIT",
            normalized_expression="MIT",
            source="spdx",
            validation_status="valid"
        )
        self.assertTrue(expr.is_leaf())
        self.assertEqual(expr.to_string(), "MIT")
        self.assertEqual(len(expr.get_all_components()), 1)
        self.assertEqual(len(expr.get_all_operators()), 0)

    def test_compound_expression(self):
        """Test creating a compound expression with AND/OR."""
        # Create parent node
        expr = LicenseExpression.objects.create(
            operator="OR",
            expression="MIT OR Apache-2.0",
            normalized_expression="MIT OR Apache-2.0",
            source="spdx",
            validation_status="valid"
        )

        # Create child nodes
        LicenseExpression.objects.create(
            parent=expr,
            component=self.mit,
            expression="MIT",
            normalized_expression="MIT",
            source="spdx",
            validation_status="valid",
            order=0
        )
        LicenseExpression.objects.create(
            parent=expr,
            component=self.apache,
            expression="Apache-2.0",
            normalized_expression="Apache-2.0",
            source="spdx",
            validation_status="valid",
            order=1
        )

        self.assertFalse(expr.is_leaf())
        self.assertEqual(expr.to_string(), "MIT OR Apache-2.0")
        self.assertEqual(len(expr.get_all_components()), 2)
        self.assertEqual(len(expr.get_all_operators()), 1)

    def test_expression_with_exception(self):
        """Test creating an expression with an exception."""
        # Create parent node
        expr = LicenseExpression.objects.create(
            operator="WITH",
            component=self.classpath,
            expression="GPL-2.0 WITH Classpath-exception-2.0",
            normalized_expression="GPL-2.0 WITH Classpath-exception-2.0",
            source="spdx",
            validation_status="valid"
        )

        # Create child node
        LicenseExpression.objects.create(
            parent=expr,
            component=self.gpl,
            expression="GPL-2.0",
            normalized_expression="GPL-2.0",
            source="spdx",
            validation_status="valid"
        )

        self.assertTrue(expr.is_exception())
        self.assertEqual(expr.to_string(), "GPL-2.0 WITH Classpath-exception-2.0")
        self.assertEqual(len(expr.get_all_components()), 2)
        self.assertEqual(len(expr.get_all_operators()), 1)

    def test_nested_expression(self):
        """Test creating a nested expression with parentheses."""
        # Create root node
        root = LicenseExpression.objects.create(
            operator="AND",
            expression="(MIT OR Apache-2.0) AND BSD-3-Clause",
            normalized_expression="(MIT OR Apache-2.0) AND BSD-3-Clause",
            source="spdx",
            validation_status="valid"
        )

        # Create OR node
        or_node = LicenseExpression.objects.create(
            parent=root,
            operator="OR",
            expression="MIT OR Apache-2.0",
            normalized_expression="MIT OR Apache-2.0",
            source="spdx",
            validation_status="valid"
        )

        # Create leaf nodes
        LicenseExpression.objects.create(
            parent=or_node,
            component=self.mit,
            expression="MIT",
            normalized_expression="MIT",
            source="spdx",
            validation_status="valid",
            order=0
        )
        LicenseExpression.objects.create(
            parent=or_node,
            component=self.apache,
            expression="Apache-2.0",
            normalized_expression="Apache-2.0",
            source="spdx",
            validation_status="valid",
            order=1
        )
        LicenseExpression.objects.create(
            parent=root,
            component=self.bsd,
            expression="BSD-3-Clause",
            normalized_expression="BSD-3-Clause",
            source="spdx",
            validation_status="valid",
            order=1
        )

        self.assertEqual(root.to_string(), "(MIT OR Apache-2.0) AND BSD-3-Clause")
        self.assertEqual(len(root.get_all_components()), 3)
        self.assertEqual(len(root.get_all_operators()), 2)

    def test_complex_nested_expression(self):
        """Test creating a complex nested expression with multiple levels."""
        # Create root node
        root = LicenseExpression.objects.create(
            operator="OR",
            expression="MIT OR (Apache-2.0 AND (BSD-3-Clause OR ISC))",
            normalized_expression="MIT OR (Apache-2.0 AND (BSD-3-Clause OR ISC))",
            source="spdx",
            validation_status="valid"
        )

        # Create MIT leaf
        LicenseExpression.objects.create(
            parent=root,
            component=self.mit,
            expression="MIT",
            normalized_expression="MIT",
            source="spdx",
            validation_status="valid",
            order=0
        )

        # Create AND node
        and_node = LicenseExpression.objects.create(
            parent=root,
            operator="AND",
            expression="Apache-2.0 AND (BSD-3-Clause OR ISC)",
            normalized_expression="Apache-2.0 AND (BSD-3-Clause OR ISC)",
            source="spdx",
            validation_status="valid"
        )

        # Create Apache leaf
        LicenseExpression.objects.create(
            parent=and_node,
            component=self.apache,
            expression="Apache-2.0",
            normalized_expression="Apache-2.0",
            source="spdx",
            validation_status="valid",
            order=0
        )

        # Create inner OR node
        inner_or = LicenseExpression.objects.create(
            parent=and_node,
            operator="OR",
            expression="BSD-3-Clause OR ISC",
            normalized_expression="BSD-3-Clause OR ISC",
            source="spdx",
            validation_status="valid"
        )

        # Create inner leaves
        LicenseExpression.objects.create(
            parent=inner_or,
            component=self.bsd,
            expression="BSD-3-Clause",
            normalized_expression="BSD-3-Clause",
            source="spdx",
            validation_status="valid",
            order=0
        )
        LicenseExpression.objects.create(
            parent=inner_or,
            component=self.isc,
            expression="ISC",
            normalized_expression="ISC",
            source="spdx",
            validation_status="valid",
            order=1
        )

        self.assertEqual(root.to_string(), "MIT OR (Apache-2.0 AND (BSD-3-Clause OR ISC))")
        self.assertEqual(len(root.get_all_components()), 4)
        self.assertEqual(len(root.get_all_operators()), 3)

    def test_invalid_expression(self):
        """Test creating an invalid expression."""
        expr = LicenseExpression.objects.create(
            expression="Invalid-License",
            normalized_expression="Invalid-License",
            source="spdx",
            validation_status="invalid",
            validation_errors=["Unknown license identifier"]
        )

        self.assertTrue(expr.is_leaf())
        self.assertEqual(expr.to_string(), "")
        self.assertEqual(len(expr.get_all_components()), 0)
        self.assertEqual(len(expr.get_all_operators()), 0)
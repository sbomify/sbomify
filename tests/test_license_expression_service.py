import pytest
from django.test import TestCase
from sboms.models import LicenseComponent, LicenseExpression
from sboms.license_expression_service import LicenseExpressionService

@pytest.mark.django_db
class TestLicenseExpressionService(TestCase):
    def setUp(self):
        self.service = LicenseExpressionService()
        # Pre-create some SPDX license components for validation
        self.mit = LicenseComponent.objects.create(identifier="MIT", name="MIT License", type="spdx")
        self.apache = LicenseComponent.objects.create(identifier="Apache-2.0", name="Apache License 2.0", type="spdx")
        self.bsd = LicenseComponent.objects.create(identifier="BSD-3-Clause", name="BSD 3-Clause License", type="spdx")
        self.gpl = LicenseComponent.objects.create(identifier="GPL-2.0", name="GNU General Public License v2.0", type="spdx")
        self.classpath = LicenseComponent.objects.create(identifier="Classpath-exception-2.0", name="Classpath Exception 2.0", type="spdx")
        self.isc = LicenseComponent.objects.create(identifier="ISC", name="ISC License", type="spdx")

    def test_validate_valid_expression(self):
        valid, errors = self.service.validate_license_expression("MIT OR Apache-2.0")
        assert valid
        assert errors == []

    def test_validate_invalid_expression(self):
        valid, warnings = self.service.validate_license_expression("MIT OR INVALID-LICENSE")
        assert valid  # Should be valid now, just with warnings
        assert warnings
        assert "Warning: Unknown license(s) or exception(s): INVALID-LICENSE" in warnings[0]

    def test_normalize_expression(self):
        norm = self.service.normalize_license_expression("MIT OR Apache-2.0")
        assert norm == "MIT OR Apache-2.0"

    def test_create_simple_license_expression_tree(self):
        root = self.service.create_license_expression_tree("MIT")
        assert root.is_leaf()
        assert root.component.identifier == "MIT"
        assert root.to_string() == "MIT"

    def test_create_compound_expression_tree(self):
        root = self.service.create_license_expression_tree("MIT OR Apache-2.0")
        assert root.operator == "OR"
        children = list(root.children.order_by("order"))
        assert len(children) == 2
        assert children[0].component.identifier == "MIT"
        assert children[1].component.identifier == "Apache-2.0"
        assert root.to_string() == "MIT OR Apache-2.0"

    def test_create_expression_with_exception_tree(self):
        root = self.service.create_license_expression_tree("GPL-2.0 WITH Classpath-exception-2.0")
        assert root.operator == "WITH"
        children = list(root.children.order_by("order"))
        assert len(children) == 2
        assert children[0].component.identifier == "GPL-2.0-only"
        assert children[1].component.identifier == "Classpath-exception-2.0"
        assert root.to_string() == "GPL-2.0-only WITH Classpath-exception-2.0"

    def test_create_nested_expression_tree(self):
        root = self.service.create_license_expression_tree("(MIT OR Apache-2.0) AND BSD-3-Clause")
        assert root.operator == "AND"
        children = list(root.children.order_by("order"))
        assert len(children) == 2
        or_node = children[0]
        assert or_node.operator == "OR"
        or_children = list(or_node.children.order_by("order"))
        assert or_children[0].component.identifier == "MIT"
        assert or_children[1].component.identifier == "Apache-2.0"
        assert children[1].component.identifier == "BSD-3-Clause"
        assert root.to_string() == "(MIT OR Apache-2.0) AND BSD-3-Clause"

    def test_create_complex_nested_expression_tree(self):
        root = self.service.create_license_expression_tree("MIT OR (Apache-2.0 AND (BSD-3-Clause OR ISC))")
        assert root.operator == "OR"
        children = list(root.children.order_by("order"))
        assert len(children) == 2
        assert children[0].component.identifier == "MIT"
        and_node = children[1]
        assert and_node.operator == "AND"
        and_children = list(and_node.children.order_by("order"))
        assert and_children[0].component.identifier == "Apache-2.0"
        inner_or = and_children[1]
        assert inner_or.operator == "OR"
        inner_or_children = list(inner_or.children.order_by("order"))
        assert inner_or_children[0].component.identifier == "BSD-3-Clause"
        assert inner_or_children[1].component.identifier == "ISC"
        assert root.to_string() == "MIT OR (Apache-2.0 AND (BSD-3-Clause OR ISC))"

    def test_create_expression_with_unknown_license(self):
        """Test that an unknown/non-SPDX license is flagged with a warning."""
        root = self.service.create_license_expression_tree("MIT OR FooBarLicense-1.0")
        assert root.operator == "OR"
        children = list(root.children.order_by("order"))
        assert len(children) == 2
        # MIT should be recognized
        assert children[0].component.identifier == "MIT"
        assert children[0].component.is_spdx is True
        # FooBarLicense-1.0 should be unrecognized but valid with warning
        assert children[1].component.identifier == "FooBarLicense-1.0"
        assert children[1].component.is_spdx is False
        assert children[1].validation_status == "warning"
        assert any("Warning: License 'FooBarLicense-1.0' is not a recognized SPDX license" in err for err in children[1].validation_errors)

    def test_spdx_canonical_identifiers(self):
        """Test that canonical SPDX identifiers are recognized as valid SPDX licenses and not deprecated."""
        valid_ids = [
            "MIT",
            "Apache-2.0",
            "BSD-3-Clause",
            "GPL-2.0-only",
            "GPL-2.0-or-later",
            "LGPL-2.1-only",
            "LGPL-2.1-or-later",
            "AGPL-3.0-only",
            "AGPL-3.0-or-later",
        ]
        for identifier in valid_ids:
            component = self.service.get_or_create_license_component(identifier)
            assert component.is_spdx, f"{identifier} should be recognized as SPDX"
            assert component.is_recognized
            assert component.type == "spdx"
            assert component.is_deprecated is False

    def test_spdx_deprecated_or_invalid_identifiers(self):
        """Test that deprecated or invalid SPDX identifiers are not recognized as valid SPDX licenses and are flagged as deprecated or custom."""
        deprecated_ids = [
            "GPL-2.0", "GPL-2.0+", "GPL-3.0", "GPL-3.0+",
            "LGPL-2.0", "LGPL-2.0+", "LGPL-2.1", "LGPL-2.1+", "LGPL-3.0", "LGPL-3.0+",
            "AGPL-1.0", "AGPL-3.0", "GFDL-1.1", "GFDL-1.2", "GFDL-1.3",
        ]
        for identifier in deprecated_ids:
            component = self.service.get_or_create_license_component(identifier)
            assert component.is_spdx, f"{identifier} should be recognized as SPDX (deprecated)"
            assert component.is_deprecated is True
            assert component.type == "spdx"
        invalid_ids = [
            "FooBarLicense-9.9",  # invalid
            "NotARealLicense",
        ]
        for identifier in invalid_ids:
            component = self.service.get_or_create_license_component(identifier)
            assert not component.is_spdx, f"{identifier} should NOT be recognized as SPDX"
            assert not component.is_recognized
            assert component.type == "custom"
            assert component.is_deprecated is False

    def test_apache_and_commons_clause(self):
        """Test that 'Apache-2.0 AND Commons-Clause' is recognized as valid."""
        is_valid, errors = self.service.validate_license_expression("Apache-2.0 AND Commons-Clause")
        assert is_valid
        # Allow the expected warning about Commons-Clause
        assert errors == [
            "Warning: Commons-Clause is not OSI or FSF approved and is not considered open source."
        ] or errors == []
        component = self.service.get_or_create_license_component("BUSL-1.1")
        assert component.is_osi_approved is False
        assert component.is_fsf_approved is False
        assert component.is_spdx is False
        assert component.is_recognized is True
        assert component.is_deprecated is False
        assert component.name == "Business Source License 1.1"
        assert component.identifier == "BUSL-1.1"
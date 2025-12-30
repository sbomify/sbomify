
import pytest
from django.template.loader import render_to_string
from sbomify.apps.core.models import Component, Project
from sbomify.apps.core.tests.e2e.factories import *  # noqa
from sbomify.apps.core.tests.shared_fixtures import *  # noqa

@pytest.mark.django_db
class TestComponentMetaInfoTemplates:
    
    def test_component_meta_info_wrapper_rendering(self, rf, component_factory, project_factory):
        # Setup
        request = rf.get("/")
        request.session = {"current_team": {"key": "test-team"}}
        project = project_factory("Test Project")
        component = component_factory(
            "Test Component", 
            Component.ComponentType.SBOM, 
            project=project
        )
        
        context = {
            "component": component,
            "request": request
        }
        
        # Test Rendering
        rendered = render_to_string("core/components/component_meta_info.html.j2", context)
        
        # Assertions
        assert "componentMetaInfoWrapper" in rendered
        assert component.id in rendered
        assert "component-meta-info-display-container" in rendered
        assert "component-meta-info-editor-container" in rendered
        assert "itemSelectModal" in rendered

    def test_component_meta_info_display_rendering(self, component_factory):
        # Setup
        metadata = {
            "supplier": {
                "name": "ACME Corp",
                "url": ["https://acme.com"],
                "address": "123 Main St",
                "contacts": [{"name": "John Doe", "email": "john@acme.com"}]
            },
            "lifecycle_phase": "build",
            "licenses": ["MIT", {"name": "Custom License"}],
            "authors": [{"name": "Jane Doe", "email": "jane@example.com"}]
        }
        
        context = {"metadata": metadata}
        
        # Test Rendering
        rendered = render_to_string("core/components/component_meta_info_display.html.j2", context)
        
        # Assertions - Check for Alpine directives as content is rendered on client side
        assert 'x-text="metadata.supplier.name"' in rendered
        assert 'x-text="formatLifecyclePhase(metadata.lifecycle_phase)"' in rendered
        assert 'x-text="author.name"' in rendered

    def test_component_meta_info_editor_rendering(self, rf, component_factory, project_factory):
        # Setup
        request = rf.get("/")
        request.session = {"current_team": {"key": "test-team"}}
        project = project_factory("Test Project")
        component = component_factory("Test Component", project=project)
        
        metadata = {
            "supplier": {"name": "ACME Corp"},
            "licenses": ["MIT"],
            "authors": []
        }
        
        contact_profiles = [
            {"id": "cp1", "name": "Profile 1", "email": "p1@example.com"}
        ]
        
        context = {
            "component": component,
            "request": request,
            "metadata": metadata,
            "contact_profiles": contact_profiles
        }
        
        # Test Rendering
        rendered = render_to_string("core/components/component_meta_info_editor.html.j2", context)
        
        # Assertions
        assert "componentMetaInfoEditor" in rendered
        assert "licensesEditor" in rendered
        assert "supplierEditor" in rendered
        assert "contactsEditor" in rendered

    def test_item_select_modal_rendering(self, component_factory, project_factory):
        # Setup
        project = project_factory("Test Project")
        component = component_factory("Test Component", project=project)
        context = {"component": component}

        # Test Rendering
        rendered = render_to_string("core/components/item_select_modal.html.j2", context)
        
        # Assertions
        assert "itemSelectModal" in rendered
        assert "Select Component" in rendered
        assert "modal-dialog" in rendered

    def test_ci_cd_info_rendering(self, component_factory, project_factory):
        # Setup
        project = project_factory("Test Project")
        component = component_factory("Test Component", project=project)
        
        context = {
            "component": component,
            "integration_status": {
                "is_active": True,
                "last_run": "2023-01-01"
            }
        }
        
        # Test Rendering
        rendered = render_to_string("sboms/components/ci_cd_info.html.j2", context)
        
        # Assertions
        assert "ciCdInfo" in rendered
        assert component.id in rendered
        assert "CI/CD Integration" in rendered

    def test_licenses_editor_rendering(self):
        # Setup
        licenses = ["MIT", "Apache-2.0"]
        unknown_tokens = ["UNKNOWN"]
        
        context = {
            "licenses": licenses,
            "unknown_tokens": unknown_tokens
        }
        
        # Test Rendering
        rendered = render_to_string("sboms/components/licenses_editor.html.j2", context)
        
        # Assertions
        assert "licensesEditor" in rendered
        assert "x-model=\"licenseExpression\"" in rendered
        
    def test_supplier_editor_rendering(self):
        # Test Rendering (wrapper and base)
        rendered = render_to_string("sboms/components/supplier_editor.html.j2", {})
        
        # Assertions
        assert "supplierEditor" in rendered
        # Check content from base, not filename
        assert "supplier.name" in rendered
        assert "supplier.address" in rendered
        assert "contactsEditor" in rendered

    def test_contacts_editor_rendering(self):
        # Test Rendering (wrapper and base)
        rendered = render_to_string("sboms/components/contacts_editor.html.j2", {})
        
        # Assertions
        assert "contactsEditor" in rendered
        
        # Check content from base
        rendered_base = render_to_string("sboms/components/contacts_editor_base.html.j2", {})
        assert "newContact.name" in rendered_base
        assert "newContact.email" in rendered_base

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.sboms.models import Component
from sbomify.apps.sboms.tests.test_views import setup_test_session


@pytest.mark.django_db
class TestComponentDetailsViews:
    def setup_method(self):
        self.client = Client()

    def test_private_bom_component_template(self, sample_team_with_owner_member, sample_user):
        """Test that private BOM component renders the correct template."""
        team = sample_team_with_owner_member.team
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, sample_user)

        component = Component.objects.create(
            name="Private BOM Component",
            team=team,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.PRIVATE,
        )

        url = reverse("core:component_details", kwargs={"component_id": component.id})
        response = self.client.get(url)

        assert response.status_code == 200
        # Verify specific template usage indirectly via content or context
        # Django test client 'response.templates' can be checked
        templates = [t.name for t in response.templates]
        assert "core/component_details_private_sbom.html.j2" in templates

    def test_private_document_component_template(self, sample_team_with_owner_member, sample_user):
        """Test that private Document component renders the correct template."""
        team = sample_team_with_owner_member.team
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, sample_user)

        component = Component.objects.create(
            name="Private Document Component",
            team=team,
            component_type=Component.ComponentType.DOCUMENT,
            visibility=Component.Visibility.PRIVATE,
        )

        url = reverse("core:component_details", kwargs={"component_id": component.id})
        response = self.client.get(url)

        assert response.status_code == 200
        templates = [t.name for t in response.templates]
        assert "core/component_details_private_document.html.j2" in templates

    def test_public_bom_component_template(self, sample_team_with_owner_member):
        """Test that public BOM component renders the correct template."""
        team = sample_team_with_owner_member.team
        component = Component.objects.create(
            name="Public BOM Component",
            team=team,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.PUBLIC,
        )

        url = reverse("core:component_details_public", kwargs={"component_id": component.id})
        response = self.client.get(url)

        assert response.status_code == 200
        templates = [t.name for t in response.templates]
        assert "core/component_details_public_sbom.html.j2" in templates

    def test_public_document_component_template(self, sample_team_with_owner_member):
        """Test that public Document component renders the correct template."""
        team = sample_team_with_owner_member.team
        component = Component.objects.create(
            name="Public Document Component",
            team=team,
            component_type=Component.ComponentType.DOCUMENT,
            visibility=Component.Visibility.PUBLIC,
        )

        url = reverse("core:component_details_public", kwargs={"component_id": component.id})
        response = self.client.get(url)

        assert response.status_code == 200
        templates = [t.name for t in response.templates]
        assert "core/component_details_public_document.html.j2" in templates

    def test_component_not_found(self, sample_team_with_owner_member, sample_user):
        """Test 404 for non-existent component."""
        team = sample_team_with_owner_member.team
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, sample_user)

        url = reverse("core:component_details", kwargs={"component_id": "999999"})
        response = self.client.get(url)
        assert response.status_code == 404

    def test_public_access_to_private_component_denied(self, sample_team_with_owner_member):
        """Test that public access to private component returns 403."""
        team = sample_team_with_owner_member.team
        component = Component.objects.create(
            name="Private Component",
            team=team,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.PRIVATE,
        )

        url = reverse("core:component_details_public", kwargs={"component_id": component.id})
        response = self.client.get(url)
        assert response.status_code == 403

    def test_component_item_sbom_template_parses(self):
        """Test that component item templates parse without syntax errors.

        This test ensures the component_item.html.j2 template and its includes
        (including assessment_results_card.html.j2 with the plugin accordion items)
        can be parsed without TemplateSyntaxError. This validates that the templates
        use valid Django template syntax (not Jinja2 macros).
        """
        from django.template import engines

        django_engine = engines["django"]

        # These templates should all parse without TemplateSyntaxError
        templates_to_test = [
            "core/component_item.html.j2",
            "plugins/components/assessment_results_card.html.j2",
            "plugins/components/_assessment_run_item.html.j2",
        ]

        for template_name in templates_to_test:
            try:
                template = django_engine.get_template(template_name)
                assert template is not None, f"Template {template_name} should be loaded"
            except Exception as e:
                pytest.fail(f"Template {template_name} failed to parse: {e}")


@pytest.mark.django_db
class TestComponentCbomIssuesTable:
    """The component page surfaces the latest CBOM's fail/warning findings as a table."""

    def setup_method(self):
        self.client = Client()

    def _component_page(self, team, user, component):
        self.client.login(username=user.username, password="test")
        setup_test_session(self.client, team, user)
        url = reverse("core:component_details", kwargs={"component_id": component.id})
        return self.client.get(url)

    def _cbom_with_run(self, team, findings, plugin_name="pqc-readiness"):
        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.sboms.models import SBOM

        component = Component.objects.create(
            name="Crypto Component",
            team=team,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.PRIVATE,
        )
        cbom = SBOM.objects.create(
            name="app-cbom",
            version="1.0",
            component=component,
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="cbom.json",
            bom_type=SBOM.BomType.CBOM,
        )
        AssessmentRun.objects.create(
            sbom=cbom,
            plugin_name=plugin_name,
            category="compliance",
            status="completed",
            result={"findings": findings},
        )
        return component, cbom

    def test_issues_exclude_pass_rows_and_sort_fail_first(self, sample_team_with_owner_member, sample_user):
        team = sample_team_with_owner_member.team
        component, cbom = self._cbom_with_run(
            team,
            findings=[
                {"title": "ML-DSA-65: Quantum-safe", "status": "pass", "severity": "info", "description": "ok"},
                {"title": "SHA-1: Deprecated", "status": "warning", "severity": "medium", "description": "sunset"},
                {
                    "title": "ECDSA-P384: Quantum-vulnerable",
                    "status": "fail",
                    "severity": "high",
                    "description": "bad",
                },
            ],
        )

        response = self._component_page(team, sample_user, component)

        assert response.status_code == 200
        issues = response.context["latest_cbom_issues"]
        assert [row["status"] for row in issues] == ["fail", "warning"]
        assert issues[0]["title"] == "ECDSA-P384: Quantum-vulnerable"
        assert response.context["latest_cbom_id"] == cbom.id
        assert b"CBOM issues" in response.content

    def test_clean_cbom_renders_no_issues_table(self, sample_team_with_owner_member, sample_user):
        team = sample_team_with_owner_member.team
        component, _ = self._cbom_with_run(
            team,
            findings=[
                {"title": "ML-KEM-768: Quantum-safe", "status": "pass", "severity": "info", "description": "ok"}
            ],
        )

        response = self._component_page(team, sample_user, component)

        assert response.status_code == 200
        assert response.context["latest_cbom_issues"] == []
        assert b"CBOM issues" not in response.content

    def test_component_without_cbom_has_no_issue_rows(self, sample_team_with_owner_member, sample_user):
        team = sample_team_with_owner_member.team
        component = Component.objects.create(
            name="Plain Component",
            team=team,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.PRIVATE,
        )

        response = self._component_page(team, sample_user, component)

        assert response.status_code == 200
        assert response.context["latest_cbom_issues"] == []

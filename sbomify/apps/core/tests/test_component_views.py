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
            findings=[{"title": "ML-KEM-768: Quantum-safe", "status": "pass", "severity": "info", "description": "ok"}],
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


@pytest.mark.django_db
class TestComponentHbomIssuesTable:
    """The component page surfaces the newest hardware artifact's structure findings."""

    def setup_method(self):
        self.client = Client()

    def _component_page(self, team, user, component):
        self.client.login(username=user.username, password="test")
        setup_test_session(self.client, team, user)
        url = reverse("core:component_details", kwargs={"component_id": component.id})
        return self.client.get(url)

    def _component(self, team, name="Hardware Component"):
        return Component.objects.create(
            name=name,
            team=team,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.PRIVATE,
        )

    def _artifact(self, component, bom_type, **kwargs):
        from sbomify.apps.sboms.models import SBOM

        return SBOM.objects.create(
            name=f"board-{bom_type}",
            version="1.0",
            component=component,
            format="cyclonedx",
            format_version="1.6",
            sbom_filename=f"{bom_type}.json",
            bom_type=bom_type,
            **kwargs,
        )

    def _run(self, artifact, findings, plugin_name="hbom-structure"):
        from sbomify.apps.plugins.models import AssessmentRun

        return AssessmentRun.objects.create(
            sbom=artifact,
            plugin_name=plugin_name,
            category="compliance",
            status="completed",
            result={"findings": findings},
        )

    def test_warning_rows_render_and_link_to_the_hbom(self, sample_team_with_owner_member, sample_user):
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        component = self._component(team)
        hbom = self._artifact(component, SBOM.BomType.HBOM, has_hardware_components=True)
        self._run(
            hbom,
            findings=[
                {"title": "COMP_HASH declared on 5 of 5 devices", "status": "pass", "severity": "info"},
                {
                    "title": "cdx:device:quantity declared on 2 of 5 devices",
                    "status": "warning",
                    "severity": "medium",
                    "description": "A part number without a count cannot be read as a parts list line.",
                    "remediation": "Add a cdx:device:quantity property to each device.",
                },
            ],
        )

        response = self._component_page(team, sample_user, component)

        assert response.status_code == 200
        issues = response.context["latest_hbom_issues"]
        assert [row["title"] for row in issues] == ["cdx:device:quantity declared on 2 of 5 devices"]
        assert issues[0]["remediation"] == "Add a cdx:device:quantity property to each device."
        assert response.context["latest_hbom_id"] == hbom.id
        assert b"HBOM issues" in response.content
        detail_url = reverse(
            "core:component_item",
            kwargs={"component_id": component.id, "item_type": "hbom", "item_id": hbom.id},
        )
        assert detail_url.encode() in response.content

    def test_clean_hbom_renders_no_card(self, sample_team_with_owner_member, sample_user):
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        component = self._component(team)
        self._run(
            self._artifact(component, SBOM.BomType.HBOM, has_hardware_components=True),
            findings=[{"title": "HBOM_AUTHOR present", "status": "pass", "severity": "info"}],
        )

        response = self._component_page(team, sample_user, component)

        assert response.status_code == 200
        assert response.context["latest_hbom_issues"] == []
        assert b"HBOM issues" not in response.content

    def test_component_without_hardware_artifact_renders_no_card(self, sample_team_with_owner_member, sample_user):
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        component = self._component(team, name="Software Only")
        self._artifact(component, SBOM.BomType.SBOM)

        response = self._component_page(team, sample_user, component)

        assert response.status_code == 200
        assert response.context["latest_hbom_issues"] == []
        assert response.context["latest_hbom_id"] is None
        assert b"HBOM issues" not in response.content

    def test_hbom_outranks_a_newer_hardware_bearing_sbom(self, sample_team_with_owner_member, sample_user):
        """A later software upload must not empty the card — the HBOM still owns the findings."""
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        component = self._component(team)
        hbom = self._artifact(component, SBOM.BomType.HBOM, has_hardware_components=True)
        self._run(hbom, findings=[{"title": "COMP_MANUFACTURER missing", "status": "warning", "severity": "medium"}])
        self._artifact(component, SBOM.BomType.SBOM, has_hardware_components=True)

        response = self._component_page(team, sample_user, component)

        assert response.status_code == 200
        assert response.context["latest_hbom_id"] == hbom.id
        assert [row["title"] for row in response.context["latest_hbom_issues"]] == ["COMP_MANUFACTURER missing"]

    def test_software_compliance_findings_do_not_reach_the_card(self, sample_team_with_owner_member, sample_user):
        """NTIA scores a mixed hardware-bearing SBOM; none of that describes the parts list."""
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        component = self._component(team)
        mixed = self._artifact(component, SBOM.BomType.SBOM, has_hardware_components=True)
        self._run(
            mixed,
            findings=[{"title": "Supplier name missing", "status": "fail", "severity": "high"}],
            plugin_name="ntia-minimum-elements-2021",
        )

        response = self._component_page(team, sample_user, component)

        assert response.status_code == 200
        assert response.context["latest_hbom_issues"] == []
        assert b"HBOM issues" not in response.content


@pytest.mark.django_db
class TestComponentItemVexAliasEnrichment:
    """The VEX detail page enriches a suppression's display id/aliases from the
    component's latest scan (Dependency-Track's CVE vs. OSV's GHSA for the same
    vulnerability). Regression coverage for the two-phase winner-id query (#1218)
    that replaced a direct DISTINCT-ON `result` projection — same behavior, cheaper
    query shape."""

    def setup_method(self):
        self.client = Client()

    def test_suppression_resolves_alias_from_latest_scan(self, sample_team_with_owner_member, sample_user, mocker):
        import json

        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        component = Component.objects.create(
            name="Aliased Component",
            team=team,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.PRIVATE,
        )
        sbom = SBOM.objects.create(
            name="app",
            version="1.0",
            component=component,
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="app.json",
            bom_type=SBOM.BomType.SBOM,
        )
        # Scanner reports the vuln under a GHSA id, with the CVE as an alias.
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="osv",
            category="security",
            status="completed",
            result={
                "findings": [
                    {
                        "id": "GHSA-xxxx",
                        "aliases": ["CVE-2021-1"],
                        "severity": "high",
                        "component": {"name": "foo", "version": "1.0.0"},
                    }
                ]
            },
        )
        vex = SBOM.objects.create(
            name="app-vex",
            version="1.0",
            component=component,
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="vex.json",
            bom_type=SBOM.BomType.VEX,
            source="manual_upload",
        )
        # The hand-authored VEX names only the CVE — the alias-enrichment must
        # pull "GHSA-xxxx" in from the scanner's finding.
        vex_doc = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "components": [
                {
                    "type": "library",
                    "name": "foo",
                    "version": "1.0.0",
                    "purl": "pkg:npm/foo@1.0.0",
                    "bom-ref": "pkg:npm/foo@1.0.0",
                }
            ],
            "vulnerabilities": [
                {
                    "id": "CVE-2021-1",
                    "analysis": {"state": "not_affected", "justification": "code_not_reachable"},
                    "affects": [{"ref": "pkg:npm/foo@1.0.0"}],
                }
            ],
        }
        mocker.patch("sbomify.apps.core.object_store.S3Client").return_value.get_sbom_data.return_value = json.dumps(
            vex_doc
        ).encode()

        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, sample_user)
        url = reverse(
            "core:component_item", kwargs={"component_id": component.id, "item_type": "vex", "item_id": vex.id}
        )
        response = self.client.get(url)

        assert response.status_code == 200
        suppressions = response.context["vex_suppressions"]
        assert len(suppressions) == 1
        assert suppressions[0]["id"] == "CVE-2021-1"
        assert suppressions[0]["aliases"] == ["GHSA-xxxx"]

    def test_sbom_page_merges_provider_counts_by_alias(self, sample_team_with_owner_member, sample_user):
        """The SBOM detail page's vulnerability summary (Block B's own two-phase
        winner-id query) merges two providers' findings for the same vulnerability
        into one count, matching the component page badge."""
        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        component = Component.objects.create(
            name="Dual Scanned Component",
            team=team,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.PRIVATE,
        )
        sbom = SBOM.objects.create(
            name="app",
            version="1.0",
            component=component,
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="app.json",
            bom_type=SBOM.BomType.SBOM,
        )
        pkg = {"name": "lodash", "version": "4.17.15", "purl": "pkg:npm/lodash@4.17.15"}
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="dependency-track",
            category="security",
            status="completed",
            result={"findings": [{"id": "CVE-2021-23337", "severity": "high", "component": pkg}]},
        )
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="osv",
            category="security",
            status="completed",
            result={
                "findings": [
                    {
                        "id": "GHSA-35jh-r3h4-6jhm",
                        "severity": "critical",
                        "aliases": ["CVE-2021-23337"],
                        "component": pkg,
                    }
                ]
            },
        )

        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, sample_user)
        url = reverse(
            "core:component_item", kwargs={"component_id": component.id, "item_type": "sboms", "item_id": sbom.id}
        )
        response = self.client.get(url)

        assert response.status_code == 200
        summary = response.context["vulnerability_summary"]
        assert summary["total"] == 1
        assert summary["critical"] == 1
        assert summary["high"] == 0


@pytest.mark.django_db
class TestComponentVulnFilterContext:
    """The internal drill-down's filter data: suppressed rows stay in the list
    (revealed by the toggle), the header counts exclude them so they reconcile
    with the Trust Center posture, and the per-row parallel lists feed the
    severity / analysis-state / KEV filters."""

    def _component_with_vex(self, team):

        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.sboms.models import SBOM

        component = Component.objects.create(
            name="Filtered Component",
            team=team,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.PRIVATE,
        )
        sbom = SBOM.objects.create(
            name="app",
            version="2.0",
            component=component,
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="app.json",
            bom_type=SBOM.BomType.SBOM,
        )
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="osv",
            category="security",
            status="completed",
            result={
                "findings": [
                    {"id": "CVE-2026-1", "severity": "critical", "component": {"name": "a", "version": "1"}},
                    {"id": "CVE-2026-2", "severity": "high", "component": {"name": "b", "version": "1"}},
                ]
            },
        )
        vex_doc = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "vulnerabilities": [
                {
                    "id": "CVE-2026-2",
                    "affects": [{"ref": "pkg:pypi/b@1"}],
                    "analysis": {"state": "not_affected", "justification": "code_not_reachable"},
                }
            ],
        }
        SBOM.objects.create(
            name="app-vex",
            version="1",
            component=component,
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="vex.json",
            bom_type=SBOM.BomType.VEX,
            source="manual_upload",
        )
        return component, vex_doc

    def test_summary_excludes_suppressed_and_lists_feed_the_filters(
        self, sample_team_with_owner_member, sample_user, mocker
    ):
        import json

        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        mocker.patch(
            "sbomify.apps.vulnerability_scanning.kev.kev_ids_for_serialization",
            return_value=frozenset({"cve-2026-1"}),
        )
        member = sample_team_with_owner_member
        component, vex_doc = self._component_with_vex(member.team)
        mocker.patch("sbomify.apps.core.object_store.S3Client").return_value.get_sbom_data.return_value = json.dumps(
            vex_doc
        ).encode()
        client = Client()
        setup_authenticated_client_session(client, member.team, sample_user)

        response = client.get(reverse("core:component_details", kwargs={"component_id": component.id}))

        assert response.status_code == 200
        context = response.context
        assert context["vuln_summary"] == {
            "total": 1,
            "critical": 1,
            "high": 0,
            "medium": 0,
            "low": 0,
            "suppressed": 1,
        }
        rows = {v["id"]: v for v in context["latest_vulns"]}
        assert rows["CVE-2026-2"]["vex_suppressed"] is True
        assert rows["CVE-2026-2"]["vex_justification"] == "code_not_reachable"
        assert rows["CVE-2026-1"]["kev"] is True
        assert context["latest_vuln_suppressed"] == [False, True]
        assert context["latest_vuln_states"] == ["open", "not_affected"]
        assert context["latest_vuln_kev"] == [True, False]

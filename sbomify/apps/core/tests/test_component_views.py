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
        (including assessment_results_card.html.j2)
        can be parsed without TemplateSyntaxError. This validates that the templates
        use valid Django template syntax (not Jinja2 macros).
        """
        from django.template import engines

        django_engine = engines["django"]

        # These templates should all parse without TemplateSyntaxError
        templates_to_test = [
            "core/component_item.html.j2",
            "plugins/components/assessment_results_card.html.j2",
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
        mocker.patch(
            "sbomify.apps.core.object_store.StorageClient"
        ).return_value.get_sbom_data.return_value = json.dumps(vex_doc).encode()

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
class TestComponentItemLargeVex:
    """A Yocto VEX carries tens of thousands of statements. The page sends them to the
    browser once as data and builds only the visible rows: a table row per statement,
    each re-filtering the whole list to decide whether it shows, froze the tab for over a
    minute at 10,000. A document that reaches the statement limit says so."""

    def setup_method(self):
        self.client = Client()

    def _vex_page(self, team, user, mocker, statements: int):
        import json

        from sbomify.apps.sboms.models import SBOM

        component = Component.objects.create(
            name=f"Yocto image {statements}", team=team, component_type=Component.ComponentType.BOM
        )
        vex = SBOM.objects.create(
            name="image-vex",
            version="1.0",
            component=component,
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="vex.json",
            bom_type=SBOM.BomType.VEX,
            source="manual_upload",
        )
        # Yocto's shape: BOM-Links into the image SBOM, no components[], so every
        # statement covers all packages.
        document = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "vulnerabilities": [
                {
                    "id": f"CVE-2024-{n:05d}",
                    "analysis": {"state": "not_affected", "justification": "code_not_present"},
                    "affects": [{"ref": f"urn:cdx:3e671687-395b-41f5-a30f-a58921a69b79/1#{n}"}],
                }
                for n in range(statements)
            ],
        }
        mocker.patch(
            "sbomify.apps.core.object_store.StorageClient"
        ).return_value.get_sbom_data.return_value = json.dumps(document).encode()
        self.client.login(username=user.username, password="test")
        setup_test_session(self.client, team, user)
        url = reverse(
            "core:component_item", kwargs={"component_id": component.id, "item_type": "vex", "item_id": vex.id}
        )
        return self.client.get(url)

    def test_the_table_does_not_grow_a_row_per_statement(self, sample_team_with_owner_member, sample_user, mocker):
        import json
        import re

        team = sample_team_with_owner_member.team
        one = self._vex_page(team, sample_user, mocker, statements=1).content.decode()
        response = self._vex_page(team, sample_user, mocker, statements=50)
        many = response.content.decode()

        assert response.status_code == 200
        assert many.count("<tr") == one.count("<tr")
        script = re.search(r'<script id="vex-suppression-rows" type="application/json">(.*?)</script>', many)
        rows = json.loads(script[1])
        assert len(rows) == 50
        assert rows[0]["id"] == "CVE-2024-00000"
        assert rows[0]["url"] == "https://www.cve.org/CVERecord?id=CVE-2024-00000"
        assert rows[0]["package"] == "All packages"
        assert "-statement limit" not in many

    def test_a_vex_at_the_statement_limit_says_the_rest_are_ignored(
        self, sample_team_with_owner_member, sample_user, mocker
    ):
        from sbomify.apps.vulnerability_scanning.vex_formats import MAX_VEX_STATEMENTS

        response = self._vex_page(
            sample_team_with_owner_member.team, sample_user, mocker, statements=MAX_VEX_STATEMENTS + 1
        )

        assert response.status_code == 200
        assert len(response.context["vex_suppressions"]) == MAX_VEX_STATEMENTS
        assert f"This VEX hits the {MAX_VEX_STATEMENTS:,}-statement limit." in response.content.decode()


@pytest.mark.django_db
class TestComponentVulnFilterContext:
    """The component page's vulnerability counts: the header excludes VEX-suppressed
    findings so it reconciles with the Trust Center posture, and the panel lists
    the same open vulnerabilities the header counts, KEV flags included."""

    def _component_with_vex(self, team, vex_version="2.0"):

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
        run = AssessmentRun.objects.create(
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
        # A VEX applies only to the SBOMs of the version it was written for,
        # so by default it speaks for the scanned SBOM's version.
        SBOM.objects.create(
            name="app-vex",
            version=vex_version,
            component=component,
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="vex.json",
            bom_type=SBOM.BomType.VEX,
            source="manual_upload",
        )
        return component, vex_doc, run

    def _component_page_context(self, member, user, mocker, **vex_kwargs):
        import json

        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
        from sbomify.apps.vulnerability_scanning.findings import sync_findings

        mocker.patch(
            "sbomify.apps.vulnerability_scanning.kev.kev_ids_for_serialization",
            return_value=frozenset({"cve-2026-1"}),
        )
        component, vex_doc, run = self._component_with_vex(member.team, **vex_kwargs)
        mocker.patch(
            "sbomify.apps.core.object_store.StorageClient"
        ).return_value.get_sbom_data.return_value = json.dumps(vex_doc).encode()
        # The panel reads the projected findings, annotated with the VEX, as the workspace list does.
        sync_findings(run)
        client = Client()
        setup_authenticated_client_session(client, member.team, user)

        response = client.get(reverse("core:component_details", kwargs={"component_id": component.id}))

        assert response.status_code == 200
        return response.context

    def test_summary_excludes_suppressed_and_the_panel_agrees(self, sample_team_with_owner_member, sample_user, mocker):
        context = self._component_page_context(sample_team_with_owner_member, sample_user, mocker)
        assert context["vuln_summary"] == {
            "total": 1,
            "critical": 1,
            "high": 0,
            "medium": 0,
            "low": 0,
            "suppressed": 1,
        }
        # The panel is the workspace Vulnerabilities list scoped to this
        # component: a suppressed vulnerability is not open, so it is not
        # listed, and its counts agree with the header's.
        vuln_data = context["vuln_data"]
        assert [row["id"] for row in vuln_data["rows"]] == ["CVE-2026-1"]
        assert vuln_data["rows"][0]["kev"] is True
        assert vuln_data["summary"]["vulnerabilities"] == context["vuln_summary"]["total"] == 1
        assert vuln_data["summary"]["critical"] == 1
        assert vuln_data["summary"]["exploited"] == 1

    def test_a_vex_for_another_version_suppresses_nothing_in_either(
        self, sample_team_with_owner_member, sample_user, mocker
    ):
        """A VEX written for version 1 does not speak for the 2.0 scan: the
        header and the panel both still count its finding as open."""
        context = self._component_page_context(sample_team_with_owner_member, sample_user, mocker, vex_version="1")

        assert context["vuln_summary"] == {
            "total": 2,
            "critical": 1,
            "high": 1,
            "medium": 0,
            "low": 0,
            "suppressed": 0,
        }
        vuln_data = context["vuln_data"]
        assert sorted(row["id"] for row in vuln_data["rows"]) == ["CVE-2026-1", "CVE-2026-2"]
        assert vuln_data["summary"]["vulnerabilities"] == context["vuln_summary"]["total"] == 2
        assert vuln_data["summary"]["high"] == 1


@pytest.mark.django_db
class TestDocumentComponentScopeControl:
    """The scope switch on a document component page.

    `ComponentScopeView` and its permission check were written and routed, and
    then nothing rendered a control that posted to them. A certification only
    earns a Trust Center badge once its component is workspace-wide, so through
    the UI alone a workspace could upload a SOC 2 report, tag it correctly,
    publish it, and never get the badge, with nothing saying why.
    """

    def setup_method(self):
        self.client = Client()

    def _document_component(self, team, *, is_global: bool) -> Component:
        return Component.objects.create(
            name="Certifications",
            team=team,
            component_type=Component.ComponentType.DOCUMENT,
            visibility=Component.Visibility.PUBLIC,
            is_global=is_global,
        )

    def _open(self, team, user, component):
        self.client.login(username=user.username, password="test")
        setup_test_session(self.client, team, user)
        response = self.client.get(reverse("core:component_details", kwargs={"component_id": component.id}))
        # Otherwise a session regression turns these into assertions about a
        # login page, which would pass or fail for the wrong reason.
        assert response.status_code == 200
        return response

    def test_a_product_scoped_document_offers_the_switch(self, sample_team_with_owner_member, sample_user):
        team = sample_team_with_owner_member.team
        component = self._document_component(team, is_global=False)

        response = self._open(team, sample_user, component)
        body = response.content.decode()

        assert reverse("core:component_scope", kwargs={"component_id": component.id}) in body
        assert 'value="workspace"' in body
        assert "Make workspace-wide" in body

    def test_a_workspace_wide_document_offers_the_way_back(self, sample_team_with_owner_member, sample_user):
        team = sample_team_with_owner_member.team
        component = self._document_component(team, is_global=True)

        body = self._open(team, sample_user, component).content.decode()

        assert 'value="product"' in body
        assert "Make product-scoped" in body

    def test_a_published_workspace_wide_document_says_it_is_on_the_trust_center(
        self, sample_team_with_owner_member, sample_user
    ):
        team = sample_team_with_owner_member.team
        component = self._document_component(team, is_global=True)

        body = self._open(team, sample_user, component).content.decode()

        assert "It appears on your Trust Center." in body

    def test_a_private_workspace_wide_document_does_not_claim_to_be_published(
        self, sample_team_with_owner_member, sample_user
    ):
        """Scope and visibility are two decisions; scope alone publishes nothing."""
        team = sample_team_with_owner_member.team
        component = self._document_component(team, is_global=True)
        component.visibility = Component.Visibility.PRIVATE
        component.save()

        body = self._open(team, sample_user, component).content.decode()

        assert "It appears on your Trust Center." not in body
        assert "Make it public or gated to show it on your Trust Center." in body

    def test_the_switch_moves_the_component(self, sample_team_with_owner_member, sample_user):
        team = sample_team_with_owner_member.team
        component = self._document_component(team, is_global=False)
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, sample_user)

        response = self.client.post(
            reverse("core:component_scope", kwargs={"component_id": component.id}),
            {"target_scope": "workspace"},
        )

        assert response.status_code == 302
        component.refresh_from_db()
        assert component.is_global is True

    def test_the_message_does_not_promise_the_trust_center_to_a_private_document(
        self, sample_team_with_owner_member, sample_user
    ):
        """The flash lands in the moment a reader is most likely to believe it."""
        team = sample_team_with_owner_member.team
        component = self._document_component(team, is_global=False)
        component.visibility = Component.Visibility.PRIVATE
        component.save()
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, sample_user)

        response = self.client.post(
            reverse("core:component_scope", kwargs={"component_id": component.id}),
            {"target_scope": "workspace"},
            follow=True,
        )

        said = [m.message for m in response.context["messages"]]
        assert "Component is now workspace-wide. Make it public or gated to show it on your Trust Center." in said

    def test_a_published_document_is_told_it_is_on_the_trust_center(self, sample_team_with_owner_member, sample_user):
        team = sample_team_with_owner_member.team
        component = self._document_component(team, is_global=False)
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, sample_user)

        response = self.client.post(
            reverse("core:component_scope", kwargs={"component_id": component.id}),
            {"target_scope": "workspace"},
            follow=True,
        )

        assert "Component is now workspace-wide and on your Trust Center." in [
            m.message for m in response.context["messages"]
        ]

    def test_a_bom_component_never_offers_it(self, sample_team_with_owner_member, sample_user):
        """Only documents can be workspace-wide, so the control must not appear."""
        team = sample_team_with_owner_member.team
        component = Component.objects.create(
            name="Firmware",
            team=team,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.PUBLIC,
        )

        body = self._open(team, sample_user, component).content.decode()

        assert reverse("core:component_scope", kwargs={"component_id": component.id}) not in body

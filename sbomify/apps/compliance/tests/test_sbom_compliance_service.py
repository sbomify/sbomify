"""Tests for the SBOM compliance service (BSI TR-03183-2 gate)."""

from __future__ import annotations

import pytest

from sbomify.apps.compliance.services.sbom_compliance_service import (
    BSI_PLUGIN_NAME,
    check_sbom_gate,
    get_bsi_assessment_status,
)
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM, Component, Product


def _create_product_with_component(team, *, component_name: str = "comp-1") -> tuple[Product, Component]:
    """Helper: create a product with a component attached directly via ProductComponent M2M."""
    product = Product.objects.create(name="Test Product", team=team)
    component = Component.objects.create(name=component_name, team=team)
    product.components.add(component)
    return product, component


def _create_sbom(component: Component, *, fmt: str = "cyclonedx", fmt_version: str = "1.6") -> SBOM:
    """Helper: create an SBOM for a component."""
    return SBOM.objects.create(
        component=component,
        name="test.cdx.json",
        format=fmt,
        format_version=fmt_version,
    )


def _create_assessment_run(
    sbom: SBOM,
    *,
    status: str = "completed",
    pass_count: int = 5,
    fail_count: int = 0,
    warning_count: int = 0,
) -> AssessmentRun:
    """Helper: create a BSI AssessmentRun for an SBOM."""
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=BSI_PLUGIN_NAME,
        plugin_version="1.0.0",
        plugin_config_hash="abc123",
        category="compliance",
        run_reason="on_upload",
        status=status,
        result={
            "summary": {
                "pass_count": pass_count,
                "fail_count": fail_count,
                "warning_count": warning_count,
            }
        },
    )


@pytest.mark.django_db
class TestGetBsiAssessmentStatus:
    """Tests for get_bsi_assessment_status()."""

    def test_no_components(self, sample_team_with_owner_member):
        """Empty product with no components returns empty result and gate=False."""
        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="Empty Product", team=team)

        result = get_bsi_assessment_status(product)

        assert result.ok
        data = result.value
        assert data["components"] == []
        assert data["summary"]["total_components"] == 0
        assert data["summary"]["components_with_sbom"] == 0
        assert data["summary"]["components_passing_bsi"] == 0
        assert data["summary"]["overall_gate"] is False

    def test_component_without_sbom(self, sample_team_with_owner_member):
        """Component with no SBOM should have has_sbom=False and gate=False."""
        team = sample_team_with_owner_member.team
        product, _component = _create_product_with_component(team)

        result = get_bsi_assessment_status(product)

        assert result.ok
        data = result.value
        assert len(data["components"]) == 1
        comp = data["components"][0]
        assert comp["has_sbom"] is False
        assert comp["sbom_format"] is None
        assert comp["sbom_format_version"] is None
        assert comp["format_compliant"] is False
        assert comp["bsi_assessment"] is None
        assert data["summary"]["overall_gate"] is False

    def test_sbom_without_bsi_assessment(self, sample_team_with_owner_member):
        """Component with SBOM but no BSI assessment should have bsi_assessment=None."""
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        _create_sbom(component)

        result = get_bsi_assessment_status(product)

        assert result.ok
        data = result.value
        comp = data["components"][0]
        assert comp["has_sbom"] is True
        assert comp["sbom_format"] == "cyclonedx"
        assert comp["bsi_assessment"] is None
        assert data["summary"]["components_with_sbom"] == 1
        assert data["summary"]["overall_gate"] is False

    def test_passing_bsi_assessment(self, sample_team_with_owner_member):
        """Component with passing BSI assessment should set gate=True."""
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        sbom = _create_sbom(component)
        _create_assessment_run(sbom, status="completed", pass_count=5, fail_count=0)

        result = get_bsi_assessment_status(product)

        assert result.ok
        data = result.value
        comp = data["components"][0]
        assert comp["bsi_assessment"] is not None
        assert comp["bsi_assessment"]["status"] == "completed"
        assert comp["bsi_assessment"]["pass_count"] == 5
        assert comp["bsi_assessment"]["fail_count"] == 0
        assert data["summary"]["components_passing_bsi"] == 1
        assert data["summary"]["overall_gate"] is True

    def test_failing_bsi_assessment(self, sample_team_with_owner_member):
        """Component with failing BSI assessment (fail_count > 0) should set gate=False."""
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        sbom = _create_sbom(component)
        _create_assessment_run(sbom, status="completed", pass_count=3, fail_count=2)

        result = get_bsi_assessment_status(product)

        assert result.ok
        data = result.value
        comp = data["components"][0]
        assert comp["bsi_assessment"]["fail_count"] == 2
        assert data["summary"]["components_passing_bsi"] == 0
        assert data["summary"]["overall_gate"] is False

    def test_failed_status_assessment(self, sample_team_with_owner_member):
        """Assessment with status=failed should not count as passing."""
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        sbom = _create_sbom(component)
        _create_assessment_run(sbom, status="failed", pass_count=0, fail_count=0)

        result = get_bsi_assessment_status(product)

        assert result.ok
        data = result.value
        assert data["summary"]["components_passing_bsi"] == 0
        assert data["summary"]["overall_gate"] is False

    def test_pending_status_assessment(self, sample_team_with_owner_member):
        """Assessment with status=pending should not count as passing."""
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        sbom = _create_sbom(component)
        _create_assessment_run(sbom, status="pending", pass_count=0, fail_count=0)

        result = get_bsi_assessment_status(product)

        assert result.ok
        data = result.value
        assert data["summary"]["components_passing_bsi"] == 0
        assert data["summary"]["overall_gate"] is False


class TestClassifyBsiFinding:
    """Issue #907: classification map tells the wizard whether a
    BSI failing check is a known tooling limitation (waiver-eligible)
    or an operator-action gap (must be fixed). Unknown finding ids
    fall back to operator_action to keep the Annex I Part II(1)
    guard strict when the BSI plugin gains a new check."""

    @pytest.mark.parametrize(
        "finding_id",
        [
            "bsi-tr03183:hash-value",
            "bsi-tr03183:executable-property",
            "bsi-tr03183:archive-property",
            "bsi-tr03183:structured-property",
            "bsi-tr03183:filename",
            "bsi-tr03183:source-code-uri",
            "bsi-tr03183:uri-deployable-form",
        ],
    )
    def test_scanner_output_gaps_are_tooling_limitations(self, finding_id):
        from sbomify.apps.compliance.services.sbom_compliance_service import _classify_bsi_finding

        remediation_type, guidance_url, human_summary = _classify_bsi_finding(finding_id)
        assert remediation_type == "tooling_limitation"
        assert guidance_url.startswith("https://")
        # Issue #907: tooling-limitation summaries must name a scanner
        # or workflow the operator recognises so they know what to
        # change. Generic "unclassified" text is NOT acceptable here.
        assert human_summary and "Unclassified" not in human_summary

    @pytest.mark.parametrize(
        "finding_id",
        [
            "bsi-tr03183:sbom-creator",
            "bsi-tr03183:component-creator",
            "bsi-tr03183:distribution-licences",
            "bsi-tr03183:unique-identifiers",
            "bsi-tr03183:no-vulnerabilities",
            "bsi-tr03183:attestation-check",
        ],
    )
    def test_authoring_gaps_are_operator_actions(self, finding_id):
        from sbomify.apps.compliance.services.sbom_compliance_service import _classify_bsi_finding

        remediation_type, _, human_summary = _classify_bsi_finding(finding_id)
        assert remediation_type == "operator_action"
        assert human_summary and "Unclassified" not in human_summary

    def test_unknown_finding_fails_closed_as_operator_action(self):
        """Conservative default: any finding id the classifier
        doesn't recognise is treated as operator_action so a new
        BSI check landing in the plugin doesn't silently unlock
        waiver eligibility."""
        from sbomify.apps.compliance.services.sbom_compliance_service import _classify_bsi_finding

        remediation_type, _, human_summary = _classify_bsi_finding("bsi-tr03183:this-does-not-exist")
        assert remediation_type == "operator_action"
        # Unknown ids get the fallback sentence — operators see "treat
        # as operator_action" which is the safer default.
        assert "Unclassified" in human_summary

    def test_attestation_check_gets_overridden_guidance_url(self):
        """Overrides point operator-action fixes to the anchored BSI
        TR-03183-2 page rather than the generic /compliance/ index."""
        from sbomify.apps.compliance.services.sbom_compliance_service import (
            _BSI_DEFAULT_GUIDANCE_URL,
            _BSI_TR03183_GUIDANCE_URL,
            _classify_bsi_finding,
        )

        _, url_default, _ = _classify_bsi_finding("bsi-tr03183:sbom-creator")
        _, url_format, _ = _classify_bsi_finding("bsi-tr03183:sbom-format")
        _, url_attest, _ = _classify_bsi_finding("bsi-tr03183:attestation-check")
        assert url_default == _BSI_DEFAULT_GUIDANCE_URL
        assert url_format == _BSI_TR03183_GUIDANCE_URL
        assert url_attest == _BSI_TR03183_GUIDANCE_URL
        assert url_format != url_default
        assert url_attest != url_default


@pytest.mark.django_db
class TestFailingCheckEnrichment:
    """The failing-checks list in ``bsi_assessment`` must carry
    ``remediation_type`` and ``guidance_url`` so the Step 2 wizard
    template can render the classification badge + docs link without
    duplicating the classifier on the front end."""

    def test_failing_check_carries_remediation_type_and_url(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        sbom = _create_sbom(component, fmt="cyclonedx", fmt_version="1.6")
        # Override the helper's empty-findings default with a concrete
        # failing check so the enrichment path runs.
        run = _create_assessment_run(sbom, pass_count=0, fail_count=1)
        run.result = {
            "summary": {"pass_count": 0, "fail_count": 1, "warning_count": 0},
            "findings": [
                {
                    "id": "bsi-tr03183:hash-value",
                    "status": "fail",
                    "title": "Hash Value (SHA-512)",
                    "description": "SHA-512 missing for apt-packaged components.",
                    "remediation": "Re-run with sbomify-action --enrich.",
                }
            ],
        }
        run.save(update_fields=["result"])

        result = get_bsi_assessment_status(product)

        assert result.ok
        check = result.value["components"][0]["bsi_assessment"]["failing_checks"][0]
        assert check["remediation_type"] == "tooling_limitation"
        assert check["guidance_url"].startswith("https://")
        # Issue #907 plain-English one-liner reaches the enriched
        # finding so the Step 2 template can render it inline.
        assert check["human_summary"]
        assert "syft" in check["human_summary"].lower()


@pytest.mark.django_db
class TestSbomifyActionFlag:
    """Issue #902: the bsi_assessment dict must surface a
    ``was_generated_by_sbomify_action`` flag so the wizard can hide the
    "See sbomify-action enrichment guide" CTA when the SBOM already came
    from that tool."""

    def _seed_tooling_limitation_run(self, sbom: SBOM) -> AssessmentRun:
        """A failing run with a tooling_limitation check — the only scenario
        where the CRA wizard needs to know whether the SBOM came from
        sbomify-action (issue #902 round 1)."""
        run = _create_assessment_run(sbom, pass_count=0, fail_count=1)
        run.result = {
            "summary": {"pass_count": 0, "fail_count": 1, "warning_count": 0},
            "findings": [
                {
                    "id": "bsi-tr03183:executable-property",
                    "status": "fail",
                    "title": "Executable Property",
                    "description": "Missing isExecutable property.",
                    "remediation": "Annotate components.",
                }
            ],
        }
        run.save(update_fields=["result"])
        return run

    def test_flag_true_when_sbom_is_from_sbomify_action(self, mocker, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        sbom = _create_sbom(component)
        self._seed_tooling_limitation_run(sbom)

        mocker.patch(
            "sbomify.apps.compliance.services.sbom_compliance_service.sbom_was_generated_by_sbomify_action",
            return_value=True,
        )

        result = get_bsi_assessment_status(product)

        assert result.ok
        assert result.value["components"][0]["bsi_assessment"]["was_generated_by_sbomify_action"] is True

    def test_flag_false_when_sbom_not_from_sbomify_action(self, mocker, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        sbom = _create_sbom(component)
        self._seed_tooling_limitation_run(sbom)

        mocker.patch(
            "sbomify.apps.compliance.services.sbom_compliance_service.sbom_was_generated_by_sbomify_action",
            return_value=False,
        )

        result = get_bsi_assessment_status(product)

        assert result.ok
        assert result.value["components"][0]["bsi_assessment"]["was_generated_by_sbomify_action"] is False


@pytest.mark.django_db
class TestSbomifyActionDetectionIsLazy:
    """Don't pay an S3 round-trip when there's no tooling-limitation CTA
    for the flag to gate. Passing assessments and failing assessments with
    only operator_action findings must not call
    ``sbom_was_generated_by_sbomify_action``."""

    def _make_run(self, sbom: SBOM, *, findings: list[dict] | None) -> AssessmentRun:
        return AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name=BSI_PLUGIN_NAME,
            plugin_version="1.0.0",
            plugin_config_hash="abc",
            category="compliance",
            run_reason="on_upload",
            status="completed",
            result={
                "summary": {"pass_count": 5 if not findings else 0, "fail_count": len(findings or [])},
                "findings": findings or [],
            },
        )

    def test_passing_run_skips_detection(self, mocker, sample_team_with_owner_member):
        from sbomify.apps.compliance.services.sbom_compliance_service import _build_bsi_assessment_dict

        team = sample_team_with_owner_member.team
        _, component = _create_product_with_component(team)
        sbom = _create_sbom(component)
        spy = mocker.patch(
            "sbomify.apps.compliance.services.sbom_compliance_service.sbom_was_generated_by_sbomify_action",
            return_value=True,
        )
        run = self._make_run(sbom, findings=None)

        dict_ = _build_bsi_assessment_dict(run, sbom=sbom)

        assert dict_["was_generated_by_sbomify_action"] is False
        spy.assert_not_called()

    def test_operator_action_only_skips_detection(self, mocker, sample_team_with_owner_member):
        """Failing checks that are all operator_action have no tooling-limitation
        CTA to gate, so the flag stays False without an S3 fetch."""
        from sbomify.apps.compliance.services.sbom_compliance_service import _build_bsi_assessment_dict

        team = sample_team_with_owner_member.team
        _, component = _create_product_with_component(team)
        sbom = _create_sbom(component)
        spy = mocker.patch(
            "sbomify.apps.compliance.services.sbom_compliance_service.sbom_was_generated_by_sbomify_action",
            return_value=True,
        )
        run = self._make_run(
            sbom,
            findings=[{"id": "bsi-tr03183:component-name", "status": "fail", "title": "Component Name"}],
        )

        dict_ = _build_bsi_assessment_dict(run, sbom=sbom)

        assert dict_["was_generated_by_sbomify_action"] is False
        spy.assert_not_called()

    def test_tooling_limitation_triggers_detection(self, mocker, sample_team_with_owner_member):
        from sbomify.apps.compliance.services.sbom_compliance_service import _build_bsi_assessment_dict

        team = sample_team_with_owner_member.team
        _, component = _create_product_with_component(team)
        sbom = _create_sbom(component)
        spy = mocker.patch(
            "sbomify.apps.compliance.services.sbom_compliance_service.sbom_was_generated_by_sbomify_action",
            return_value=True,
        )
        run = self._make_run(
            sbom,
            findings=[
                {
                    "id": "bsi-tr03183:executable-property",
                    "status": "fail",
                    "title": "Executable Property",
                }
            ],
        )

        dict_ = _build_bsi_assessment_dict(run, sbom=sbom)

        assert dict_["was_generated_by_sbomify_action"] is True
        spy.assert_called_once_with(sbom)


@pytest.mark.django_db
class TestFormatCompliance:
    """Tests for SBOM format version compliance checking."""

    def test_cyclonedx_1_6_compliant(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        _create_sbom(component, fmt="cyclonedx", fmt_version="1.6")

        result = get_bsi_assessment_status(product)
        assert result.value["components"][0]["format_compliant"] is True

    def test_cyclonedx_1_5_not_compliant(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team, component_name="comp-cdx15")
        _create_sbom(component, fmt="cyclonedx", fmt_version="1.5")

        result = get_bsi_assessment_status(product)
        assert result.value["components"][0]["format_compliant"] is False

    def test_spdx_3_0_1_compliant(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team, component_name="comp-spdx301")
        _create_sbom(component, fmt="spdx", fmt_version="3.0.1")

        result = get_bsi_assessment_status(product)
        assert result.value["components"][0]["format_compliant"] is True

    def test_spdx_2_3_not_compliant(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team, component_name="comp-spdx23")
        _create_sbom(component, fmt="spdx", fmt_version="2.3")

        result = get_bsi_assessment_status(product)
        assert result.value["components"][0]["format_compliant"] is False

    def test_cyclonedx_1_7_compliant(self, sample_team_with_owner_member):
        """Versions above the minimum should also be compliant."""
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team, component_name="comp-cdx17")
        _create_sbom(component, fmt="cyclonedx", fmt_version="1.7")

        result = get_bsi_assessment_status(product)
        assert result.value["components"][0]["format_compliant"] is True

    def test_unknown_format_not_compliant(self, sample_team_with_owner_member):
        """Unknown SBOM formats should not be considered compliant."""
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team, component_name="comp-unknown")
        _create_sbom(component, fmt="unknown", fmt_version="1.0")

        result = get_bsi_assessment_status(product)
        assert result.value["components"][0]["format_compliant"] is False


@pytest.mark.django_db
class TestCheckSbomGate:
    """Tests for check_sbom_gate()."""

    def test_gate_false_no_components(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="Empty Gate Product", team=team)

        result = check_sbom_gate(product)
        assert result.ok
        assert result.value is False

    def test_gate_true_with_passing_assessment(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team, component_name="gate-pass")
        sbom = _create_sbom(component)
        _create_assessment_run(sbom, status="completed", fail_count=0)

        result = check_sbom_gate(product)
        assert result.ok
        assert result.value is True

    def test_gate_false_with_failing_assessment(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team, component_name="gate-fail")
        sbom = _create_sbom(component)
        _create_assessment_run(sbom, status="completed", fail_count=3)

        result = check_sbom_gate(product)
        assert result.ok
        assert result.value is False

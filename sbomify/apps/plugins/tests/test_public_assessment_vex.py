"""A VEX uploaded after a release must not take the release's badges off the trust center.

No plugin assesses a VEX, so it never has runs. Picking a component's latest
artifact by upload time alone made a triage VEX the "latest SBOM", and a
component with no runs drops out of the product's intersection, leaving the
product with no badges at all.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from sbomify.apps.core.models import Component, Product
from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin
from sbomify.apps.plugins.public_assessment_utils import (
    get_component_assessment_status,
    get_component_latest_sbom_assessment_status,
    get_components_latest_sbom_assessments_batch,
    get_product_latest_sbom_assessment_status,
    get_products_latest_sbom_assessments_batch,
)
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason, RunStatus
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Workspace

PLUGIN = "ntia-minimum-elements-2021"


@pytest.fixture
def component(db):
    RegisteredPlugin.objects.get_or_create(
        name=PLUGIN,
        defaults={
            "display_name": "NTIA",
            "category": AssessmentCategory.COMPLIANCE.value,
            "version": "1.0.0",
            "plugin_class_path": "sbomify.apps.plugins.builtins.ntia.NTIAMinimumElementsPlugin",
            "is_enabled": True,
        },
    )
    team = Workspace.objects.create(name="VEX Team", key="vex-team", is_public=True)
    component = Component.objects.create(
        name="Container", team=team, visibility=Component.Visibility.PUBLIC, component_type="bom"
    )
    sbom = SBOM.objects.create(
        name="Container", version="1.0.0", component=component, format="cyclonedx", format_version="1.6"
    )
    AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=PLUGIN,
        plugin_version="1.0.0",
        plugin_config_hash="h",
        category=AssessmentCategory.COMPLIANCE.value,
        run_reason=RunReason.ON_UPLOAD.value,
        status=RunStatus.COMPLETED.value,
        result={"summary": {"pass_count": 7, "fail_count": 0, "error_count": 0}},
    )
    vex = SBOM.objects.create(
        name="Container",
        version="triage-1",
        component=component,
        format="cyclonedx",
        format_version="1.6",
        bom_type=SBOM.BomType.VEX,
    )
    SBOM.objects.filter(pk=vex.pk).update(created_at=timezone.now() + timedelta(minutes=30))
    return component


@pytest.fixture
def product(component):
    product = Product.objects.create(name="Product", team=component.team, is_public=True)
    product.components.add(component)
    return product


def _names(assessments) -> set[str]:
    return {a.plugin_name for a in assessments}


@pytest.mark.django_db
class TestVexDoesNotHideBadges:
    def test_product_listing(self, product):
        result = get_products_latest_sbom_assessments_batch([product])

        assert _names(result[str(product.id)]) == {PLUGIN}

    def test_product_page(self, product):
        assert _names(get_product_latest_sbom_assessment_status(product).passing_assessments) == {PLUGIN}

    def test_component_listing(self, component):
        result = get_components_latest_sbom_assessments_batch([component])

        assert _names(result[str(component.id)]) == {PLUGIN}

    def test_component_latest_sbom(self, component):
        assert _names(get_component_latest_sbom_assessment_status(component).passing_assessments) == {PLUGIN}

    def test_component_page(self, component):
        assert _names(get_component_assessment_status(component).passing_assessments) == {PLUGIN}

    def test_a_component_with_only_a_vex_has_no_assessments(self, component):
        SBOM.objects.filter(component=component, bom_type=SBOM.BomType.SBOM).delete()

        status = get_component_latest_sbom_assessment_status(component)

        assert not status.has_assessments
        assert status.passing_assessments == []

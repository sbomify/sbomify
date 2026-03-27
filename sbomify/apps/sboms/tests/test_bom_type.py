import pytest
from django.db import IntegrityError

from sbomify.apps.sboms.models import SBOM, Component


@pytest.mark.django_db
class TestBomTypeField:
    def test_sbom_has_bom_type_field_defaulting_to_sbom(self, sample_component: Component):
        sbom = SBOM.objects.create(
            name="test",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="t.json",
            component=sample_component,
            source="test",
        )
        assert sbom.bom_type == "sbom"

    def test_sbom_accepts_bom_type_vex(self, sample_component: Component):
        vex = SBOM.objects.create(
            name="test-vex",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="v.json",
            component=sample_component,
            source="test",
            bom_type="vex",
        )
        assert vex.bom_type == "vex"

    def test_sbom_and_vex_coexist_same_component_version_format(self, sample_component: Component):
        SBOM.objects.create(
            name="sbom",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="s.json",
            component=sample_component,
            source="test",
            bom_type="sbom",
        )
        vex = SBOM.objects.create(
            name="vex",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="v.json",
            component=sample_component,
            source="test",
            bom_type="vex",
        )
        assert vex.pk is not None

    @pytest.mark.django_db(transaction=True)
    def test_duplicate_bom_type_raises_integrity_error(self, sample_component: Component):
        SBOM.objects.create(
            name="s1",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="s1.json",
            component=sample_component,
            source="test",
            bom_type="sbom",
        )
        with pytest.raises(IntegrityError):
            SBOM.objects.create(
                name="s2",
                version="1.0.0",
                format="cyclonedx",
                format_version="1.6",
                sbom_filename="s2.json",
                component=sample_component,
                source="test",
                bom_type="sbom",
            )

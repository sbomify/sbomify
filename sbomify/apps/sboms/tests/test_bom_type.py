import pytest
from django.db import IntegrityError

from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.sboms.services.sboms import serialize_sbom


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


@pytest.mark.django_db
class TestBomTypeSerialization:
    def test_serialize_sbom_includes_bom_type(self, sample_component: Component):
        sbom = SBOM.objects.create(
            name="t",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="t.json",
            component=sample_component,
            source="test",
            bom_type="vex",
        )
        assert serialize_sbom(sbom)["bom_type"] == "vex"

    def test_serialize_sbom_default_bom_type(self, sample_component: Component):
        sbom = SBOM.objects.create(
            name="t",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="t.json",
            component=sample_component,
            source="test",
        )
        assert serialize_sbom(sbom)["bom_type"] == "sbom"


@pytest.mark.django_db
class TestBomTypeComponentUpgrade:
    def test_component_type_unchanged_for_sbom_upload(self, sample_component: Component):
        """Uploading bom_type=sbom should not change component_type."""
        assert sample_component.component_type == Component.ComponentType.SBOM
        SBOM.objects.create(
            name="test",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="t.json",
            component=sample_component,
            source="test",
            bom_type="sbom",
        )
        sample_component.refresh_from_db()
        assert sample_component.component_type == Component.ComponentType.SBOM

    def test_component_type_upgrades_to_bom_for_vex(self, sample_component: Component):
        """Uploading bom_type=vex should upgrade component_type from sbom to bom."""
        from sbomify.apps.sboms.apis import _maybe_upgrade_component_type

        assert sample_component.component_type == Component.ComponentType.SBOM
        SBOM.objects.create(
            name="test-vex",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="v.json",
            component=sample_component,
            source="test",
            bom_type="vex",
        )
        _maybe_upgrade_component_type(sample_component, "vex")
        sample_component.refresh_from_db()
        assert sample_component.component_type == Component.ComponentType.BOM


@pytest.mark.django_db
class TestLatestSbomWithBomType:
    def test_latest_sbom_property_returns_newest_regardless_of_bom_type(self, sample_component: Component):
        """Component.latest_sbom returns the newest SBOM record by created_at."""
        SBOM.objects.create(
            name="old-sbom",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="s.json",
            component=sample_component,
            source="test",
            bom_type="sbom",
        )
        vex = SBOM.objects.create(
            name="new-vex",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="v.json",
            component=sample_component,
            source="test",
            bom_type="vex",
        )
        # latest_sbom returns newest by created_at, which is the VEX
        assert sample_component.latest_sbom.id == vex.id

    def test_filtering_by_bom_type_returns_correct_latest(self, sample_component: Component):
        """Filtering by bom_type=sbom returns only actual SBOMs."""
        sbom = SBOM.objects.create(
            name="old-sbom",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="s.json",
            component=sample_component,
            source="test",
            bom_type="sbom",
        )
        SBOM.objects.create(
            name="newer-vex",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="v.json",
            component=sample_component,
            source="test",
            bom_type="vex",
        )
        # Filtering by bom_type=sbom should return only the SBOM
        latest_actual_sbom = (
            sample_component.sbom_set.filter(bom_type=SBOM.BomType.SBOM).order_by("-created_at").first()
        )
        assert latest_actual_sbom.id == sbom.id

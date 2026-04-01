import pytest
from django.db import IntegrityError

from sbomify.apps.sboms.apis import _validate_bom_type
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
class TestLatestSbomWithBomType:
    def test_latest_sbom_property_filters_by_sbom_bom_type(self, sample_component: Component):
        """Component.latest_sbom returns only actual SBOMs, not VEX/CBOM."""
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
            name="new-vex",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="v.json",
            component=sample_component,
            source="test",
            bom_type="vex",
        )
        # latest_sbom filters by bom_type=sbom, so VEX is excluded
        assert sample_component.latest_sbom.id == sbom.id

    def test_latest_bom_artifact_returns_newest_regardless_of_bom_type(self, sample_component: Component):
        """Component.latest_bom_artifact returns the newest record regardless of bom_type."""
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
        assert sample_component.latest_bom_artifact.id == vex.id

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


@pytest.mark.django_db
class TestValidateBomType:
    def test_valid_bom_types_return_none(self):
        """All valid BomType enum values should pass validation."""
        for choice_value, _ in SBOM.BomType.choices:
            assert _validate_bom_type(choice_value) is None

    def test_invalid_bom_type_returns_400(self):
        """Invalid bom_type should return a 400 error tuple."""
        result = _validate_bom_type("invalid")
        assert result is not None
        status, body = result
        assert status == 400
        assert "Invalid bom_type" in body["detail"]

    def test_bom_is_not_valid_bom_type(self):
        """'bom' is not in BomType enum — should be rejected."""
        result = _validate_bom_type("bom")
        assert result is not None
        assert result[0] == 400

"""
Tests for the SBOM builder factory and format-specific builders.

These tests verify:
- Builder factory correctly selects builders based on format and version
- CycloneDX builders produce valid output for versions 1.6 and 1.7
- SPDX builder produces valid SPDX 2.3 output
- Format-aware SBOM selection works correctly
- Compliance fields are present in generated SBOMs
"""

import pytest

from sbomify.apps.sboms.builders import (
    ProjectCycloneDX16Builder,
    ProjectCycloneDX17Builder,
    ProjectSPDX23Builder,
    ReleaseCycloneDX16Builder,
    ReleaseCycloneDX17Builder,
    ReleaseSPDX23Builder,
    SBOMFormat,
    SBOMVersion,
    get_sbom_builder,
    get_supported_output_formats,
)


class TestBuilderFactory:
    """Tests for the get_sbom_builder factory function."""

    def test_get_supported_output_formats(self):
        """Test that supported formats are correctly returned."""
        formats = get_supported_output_formats()

        assert "cyclonedx" in formats
        assert "spdx" in formats
        assert "1.6" in formats["cyclonedx"]
        assert "1.7" in formats["cyclonedx"]
        assert "2.3" in formats["spdx"]

    def test_factory_returns_cdx_16_builder(self):
        """Test factory returns CycloneDX 1.6 builder."""
        builder = get_sbom_builder("release", SBOMFormat.CYCLONEDX, SBOMVersion.CDX_1_6)

        assert isinstance(builder, ReleaseCycloneDX16Builder)
        assert builder.format == SBOMFormat.CYCLONEDX
        assert builder.version == "1.6"

    def test_factory_returns_cdx_17_builder(self):
        """Test factory returns CycloneDX 1.7 builder."""
        builder = get_sbom_builder("release", SBOMFormat.CYCLONEDX, SBOMVersion.CDX_1_7)

        assert isinstance(builder, ReleaseCycloneDX17Builder)
        assert builder.format == SBOMFormat.CYCLONEDX
        assert builder.version == "1.7"

    def test_factory_returns_spdx_23_builder(self):
        """Test factory returns SPDX 2.3 builder."""
        builder = get_sbom_builder("release", SBOMFormat.SPDX, SBOMVersion.SPDX_2_3)

        assert isinstance(builder, ReleaseSPDX23Builder)
        assert builder.format == SBOMFormat.SPDX
        assert builder.version == "2.3"

    def test_factory_accepts_string_format(self):
        """Test factory accepts string format parameter."""
        builder = get_sbom_builder("release", "cyclonedx", "1.6")

        assert isinstance(builder, ReleaseCycloneDX16Builder)

    def test_factory_accepts_string_spdx_format(self):
        """Test factory accepts string SPDX format."""
        builder = get_sbom_builder("release", "spdx", "2.3")

        assert isinstance(builder, ReleaseSPDX23Builder)

    def test_factory_default_cdx_version(self):
        """Test factory uses default CDX version when not specified."""
        builder = get_sbom_builder("release", SBOMFormat.CYCLONEDX)

        # Default is CDX 1.6
        assert isinstance(builder, ReleaseCycloneDX16Builder)
        assert builder.version == "1.6"

    def test_factory_default_spdx_version(self):
        """Test factory uses default SPDX version when not specified."""
        builder = get_sbom_builder("release", SBOMFormat.SPDX)

        # Default is SPDX 2.3
        assert isinstance(builder, ReleaseSPDX23Builder)
        assert builder.version == "2.3"

    def test_factory_raises_for_unsupported_combination(self):
        """Test factory raises ValueError for unsupported combinations."""
        with pytest.raises(ValueError) as exc_info:
            get_sbom_builder("release", "cyclonedx", "9.9")

        # Error can be from enum validation or from builder registry
        assert "9.9" in str(exc_info.value) or "Unsupported" in str(exc_info.value)

    def test_factory_raises_for_unsupported_entity_type(self):
        """Test factory raises ValueError for unsupported entity types."""
        with pytest.raises(ValueError) as exc_info:
            get_sbom_builder("unknown_entity", SBOMFormat.CYCLONEDX, SBOMVersion.CDX_1_6)

        assert "Unsupported" in str(exc_info.value)

    def test_factory_passes_entity_and_user(self):
        """Test factory passes entity and user to builder."""
        mock_entity = "mock_release"
        mock_user = "mock_user"

        builder = get_sbom_builder(
            "release", SBOMFormat.CYCLONEDX, SBOMVersion.CDX_1_6, entity=mock_entity, user=mock_user
        )

        assert builder.entity == mock_entity
        assert builder.user == mock_user

    def test_factory_returns_project_cdx_16_builder(self) -> None:
        """Test factory returns CycloneDX 1.6 builder for projects."""
        builder = get_sbom_builder("project", SBOMFormat.CYCLONEDX, SBOMVersion.CDX_1_6)

        assert isinstance(builder, ProjectCycloneDX16Builder)
        assert builder.format == SBOMFormat.CYCLONEDX
        assert builder.version == "1.6"

    def test_factory_returns_project_cdx_17_builder(self) -> None:
        """Test factory returns CycloneDX 1.7 builder for projects."""
        builder = get_sbom_builder("project", SBOMFormat.CYCLONEDX, SBOMVersion.CDX_1_7)

        assert isinstance(builder, ProjectCycloneDX17Builder)
        assert builder.format == SBOMFormat.CYCLONEDX
        assert builder.version == "1.7"

    def test_factory_returns_project_spdx_23_builder(self) -> None:
        """Test factory returns SPDX 2.3 builder for projects."""
        builder = get_sbom_builder("project", SBOMFormat.SPDX, SBOMVersion.SPDX_2_3)

        assert isinstance(builder, ProjectSPDX23Builder)
        assert builder.format == SBOMFormat.SPDX
        assert builder.version == "2.3"

    def test_factory_accepts_string_project_format(self) -> None:
        """Test factory accepts string format for projects."""
        builder = get_sbom_builder("project", "cyclonedx", "1.6")

        assert isinstance(builder, ProjectCycloneDX16Builder)

    def test_factory_accepts_string_project_spdx_format(self) -> None:
        """Test factory accepts string SPDX format for projects."""
        builder = get_sbom_builder("project", "spdx", "2.3")

        assert isinstance(builder, ProjectSPDX23Builder)


class TestBuilderBaseClasses:
    """Tests for builder base classes."""

    def test_cdx_builder_has_correct_format(self):
        """Test CycloneDX builder has correct format property."""
        builder = ReleaseCycloneDX16Builder()
        assert builder.format == SBOMFormat.CYCLONEDX

    def test_spdx_builder_has_correct_format(self):
        """Test SPDX builder has correct format property."""
        builder = ReleaseSPDX23Builder()
        assert builder.format == SBOMFormat.SPDX

    def test_project_cdx_builder_has_correct_format(self) -> None:
        """Test project CycloneDX builder has correct format property."""
        builder = ProjectCycloneDX16Builder()
        assert builder.format == SBOMFormat.CYCLONEDX

    def test_project_spdx_builder_has_correct_format(self) -> None:
        """Test project SPDX builder has correct format property."""
        builder = ProjectSPDX23Builder()
        assert builder.format == SBOMFormat.SPDX

    def test_cdx_16_mixin_provides_correct_spec(self):
        """Test CycloneDX 1.6 mixin provides correct spec version."""
        builder = ReleaseCycloneDX16Builder()
        assert builder.spec_version == "1.6"
        assert builder.version == "1.6"
        assert "1.6" in builder.schema_url

    def test_cdx_17_mixin_provides_correct_spec(self):
        """Test CycloneDX 1.7 mixin provides correct spec version."""
        builder = ReleaseCycloneDX17Builder()
        assert builder.spec_version == "1.7"
        assert builder.version == "1.7"
        assert "1.7" in builder.schema_url

    def test_spdx_23_mixin_provides_correct_version(self):
        """Test SPDX 2.3 mixin provides correct version string."""
        builder = ReleaseSPDX23Builder()
        assert builder.version == "2.3"
        assert builder.spdx_version_string == "SPDX-2.3"

    def test_builder_get_tool_info(self):
        """Test builders return correct tool info."""
        builder = ReleaseCycloneDX16Builder()
        tool_info = builder.get_tool_info()

        assert "vendor" in tool_info
        assert "name" in tool_info
        assert "version" in tool_info
        assert tool_info["name"] == "sbomify"


class TestFormatAwareSBOMSelection:
    """Tests for format-aware SBOM selection utility."""

    def test_select_sbom_by_format_prefers_matching_format(self):
        """Test select_sbom_by_format prefers matching format."""
        from sbomify.apps.sboms.utils import select_sbom_by_format

        # Create mock SBOM objects
        class MockSBOM:
            def __init__(self, format, created_at="2024-01-01"):
                self.format = format
                self.created_at = created_at

        sboms = [
            MockSBOM("cyclonedx", "2024-01-01"),
            MockSBOM("spdx", "2024-01-02"),
            MockSBOM("cyclonedx", "2024-01-03"),
        ]

        # Prefer CDX
        result = select_sbom_by_format(sboms, preferred_format="cyclonedx")
        assert result.format == "cyclonedx"
        assert result.created_at == "2024-01-03"  # Most recent CDX

        # Prefer SPDX
        result = select_sbom_by_format(sboms, preferred_format="spdx")
        assert result.format == "spdx"

    def test_select_sbom_by_format_falls_back(self):
        """Test select_sbom_by_format falls back to other format."""
        from sbomify.apps.sboms.utils import select_sbom_by_format

        class MockSBOM:
            def __init__(self, format, created_at="2024-01-01"):
                self.format = format
                self.created_at = created_at

        sboms = [MockSBOM("cyclonedx")]

        # Request SPDX but only CDX available
        result = select_sbom_by_format(sboms, preferred_format="spdx", fallback=True)
        assert result.format == "cyclonedx"

    def test_select_sbom_by_format_no_fallback(self):
        """Test select_sbom_by_format returns None when no fallback."""
        from sbomify.apps.sboms.utils import select_sbom_by_format

        class MockSBOM:
            def __init__(self, format, created_at="2024-01-01"):
                self.format = format
                self.created_at = created_at

        sboms = [MockSBOM("cyclonedx")]

        # Request SPDX but only CDX available, no fallback
        result = select_sbom_by_format(sboms, preferred_format="spdx", fallback=False)
        assert result is None

    def test_select_sbom_by_format_empty_list(self):
        """Test select_sbom_by_format handles empty list."""
        from sbomify.apps.sboms.utils import select_sbom_by_format

        result = select_sbom_by_format([], preferred_format="cyclonedx")
        assert result is None

    def test_builder_select_best_sbom_uses_format_preference(self):
        """Test builder's select_best_sbom uses correct format preference."""

        class MockSBOM:
            def __init__(self, format, created_at="2024-01-01"):
                self.format = format
                self.created_at = created_at

        sboms = [
            MockSBOM("cyclonedx", "2024-01-01"),
            MockSBOM("spdx", "2024-01-02"),
        ]

        # CDX builder should prefer CDX SBOMs
        cdx_builder = ReleaseCycloneDX16Builder()
        result = cdx_builder.select_best_sbom(sboms)
        assert result.format == "cyclonedx"

        # SPDX builder should prefer SPDX SBOMs
        spdx_builder = ReleaseSPDX23Builder()
        result = spdx_builder.select_best_sbom(sboms)
        assert result.format == "spdx"


@pytest.mark.django_db
class TestSPDXOutputIntegration:
    """Integration tests for SPDX SBOM generation and validation."""

    def test_spdx_builder_generates_valid_spdx_document(self):
        """Test that SPDX builder generates a valid SPDX 2.3 document."""
        from sbomify.apps.sboms.sbom_format_schemas import spdx_2_3 as spdx23

        # Create a minimal mock release
        class MockQuerySet:
            def all(self):
                return []

        class MockProduct:
            id = "prod-123"
            name = "Test Product"
            website_url = None
            support_url = None
            security_contact = None
            links = MockQuerySet()

        class MockArtifactQuerySet:
            def filter(self, **kwargs):
                return self

            def select_related(self, *args):
                return self

            def prefetch_related(self, *args):
                return []

        class MockRelease:
            id = "rel-123"
            name = "v1.0.0"
            product = MockProduct()
            artifacts = MockArtifactQuerySet()

        # Build SPDX SBOM
        builder = ReleaseSPDX23Builder(entity=MockRelease())
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            sbom = builder(Path(temp_dir))

            # Verify it returns an SPDX Pydantic model
            assert isinstance(sbom, spdx23.SPDXDocument)

            # Verify required SPDX fields
            assert sbom.spdxVersion == "SPDX-2.3"
            assert sbom.SPDXID == "SPDXRef-DOCUMENT"
            assert sbom.dataLicense == "CC0-1.0"
            assert "sbomify" in sbom.name.lower() or "test product" in sbom.name.lower()
            assert sbom.documentNamespace.startswith("https://sbomify.com/spdx/")

            # Verify creation info
            assert sbom.creationInfo is not None
            assert sbom.creationInfo.created is not None
            assert len(sbom.creationInfo.creators) >= 1

            # Verify at least one package (the main package)
            assert sbom.packages is not None
            assert len(sbom.packages) >= 1

            # Verify documentDescribes exists
            assert sbom.documentDescribes is not None

    def test_spdx_output_serializes_correctly(self):
        """Test that SPDX output serializes to valid JSON matching schema."""
        import json

        from sbomify.apps.sboms.sbom_format_schemas import spdx_2_3 as spdx23

        class MockQuerySet:
            def all(self):
                return []

        class MockProduct:
            id = "prod-456"
            name = "Serialization Test"
            website_url = None
            support_url = None
            security_contact = None
            links = MockQuerySet()

        class MockArtifactQuerySet:
            def filter(self, **kwargs):
                return self

            def select_related(self, *args):
                return self

            def prefetch_related(self, *args):
                return []

        class MockRelease:
            id = "rel-456"
            name = "v2.0.0"
            product = MockProduct()
            artifacts = MockArtifactQuerySet()

        builder = ReleaseSPDX23Builder(entity=MockRelease())
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            sbom = builder(Path(temp_dir))

            # Serialize to JSON
            json_str = sbom.model_dump_json(indent=2, exclude_none=True, exclude_unset=True, by_alias=True)

            # Parse the JSON to verify it's valid
            parsed = json.loads(json_str)

            # Verify key fields in serialized output
            assert parsed["spdxVersion"] == "SPDX-2.3"
            assert parsed["SPDXID"] == "SPDXRef-DOCUMENT"
            assert parsed["dataLicense"] == "CC0-1.0"
            assert "name" in parsed
            assert "documentNamespace" in parsed
            assert "creationInfo" in parsed
            assert "packages" in parsed

            # Verify it can be re-parsed by the strict schema
            revalidated = spdx23.SPDXDocument.model_validate(parsed)
            assert revalidated.spdxVersion == "SPDX-2.3"

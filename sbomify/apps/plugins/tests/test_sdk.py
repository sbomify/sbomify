"""Tests for the plugin SDK (enums, dataclasses, base class)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from sbomify.apps.plugins.sdk.base import AssessmentPlugin
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason, RunStatus
from sbomify.apps.plugins.sdk.results import (
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
)


class TestAssessmentCategory:
    """Tests for AssessmentCategory enum."""

    def test_category_values(self) -> None:
        """Test that all expected categories exist with correct values."""
        assert AssessmentCategory.SECURITY.value == "security"
        assert AssessmentCategory.LICENSE.value == "license"
        assert AssessmentCategory.COMPLIANCE.value == "compliance"
        assert AssessmentCategory.ATTESTATION.value == "attestation"

    def test_category_is_string_enum(self) -> None:
        """Test that AssessmentCategory inherits from str."""
        assert isinstance(AssessmentCategory.SECURITY, str)
        assert AssessmentCategory.SECURITY == "security"


class TestRunStatus:
    """Tests for RunStatus enum."""

    def test_status_values(self) -> None:
        """Test that all expected statuses exist with correct values."""
        assert RunStatus.PENDING.value == "pending"
        assert RunStatus.RUNNING.value == "running"
        assert RunStatus.COMPLETED.value == "completed"
        assert RunStatus.FAILED.value == "failed"

    def test_status_is_string_enum(self) -> None:
        """Test that RunStatus inherits from str."""
        assert isinstance(RunStatus.PENDING, str)
        assert RunStatus.PENDING == "pending"


class TestRunReason:
    """Tests for RunReason enum."""

    def test_reason_values(self) -> None:
        """Test that all expected reasons exist with correct values."""
        assert RunReason.ON_UPLOAD.value == "on_upload"
        assert RunReason.SCHEDULED_REFRESH.value == "scheduled_refresh"
        assert RunReason.MANUAL.value == "manual"
        assert RunReason.CONFIG_CHANGE.value == "config_change"
        assert RunReason.PLUGIN_UPDATE.value == "plugin_update"

    def test_reason_is_string_enum(self) -> None:
        """Test that RunReason inherits from str."""
        assert isinstance(RunReason.ON_UPLOAD, str)
        assert RunReason.ON_UPLOAD == "on_upload"


class TestPluginMetadata:
    """Tests for PluginMetadata dataclass."""

    def test_create_metadata(self) -> None:
        """Test creating PluginMetadata with all fields."""
        metadata = PluginMetadata(
            name="test-plugin",
            version="1.0.0",
            category=AssessmentCategory.COMPLIANCE,
        )

        assert metadata.name == "test-plugin"
        assert metadata.version == "1.0.0"
        assert metadata.category == AssessmentCategory.COMPLIANCE

    def test_to_dict(self) -> None:
        """Test converting PluginMetadata to dictionary."""
        metadata = PluginMetadata(
            name="test-plugin",
            version="1.0.0",
            category=AssessmentCategory.SECURITY,
        )

        result = metadata.to_dict()

        assert result == {
            "name": "test-plugin",
            "version": "1.0.0",
            "category": "security",
        }


class TestFinding:
    """Tests for Finding dataclass."""

    def test_create_minimal_finding(self) -> None:
        """Test creating Finding with only required fields."""
        finding = Finding(
            id="test:finding",
            title="Test Finding",
            description="A test finding",
        )

        assert finding.id == "test:finding"
        assert finding.title == "Test Finding"
        assert finding.description == "A test finding"
        assert finding.severity == "info"  # default
        assert finding.status is None

    def test_create_compliance_finding(self) -> None:
        """Test creating a compliance-style finding with status."""
        finding = Finding(
            id="ntia:supplier-present",
            title="Supplier Information Present",
            description="SBOM contains supplier information",
            status="pass",
        )

        assert finding.status == "pass"

    def test_create_security_finding(self) -> None:
        """Test creating a security-style finding with severity and CVSS."""
        finding = Finding(
            id="CVE-2024-1234",
            title="Critical Vulnerability",
            description="A critical vulnerability was found",
            severity="critical",
            cvss_score=9.8,
            references=["https://nvd.nist.gov/vuln/detail/CVE-2024-1234"],
            aliases=["GHSA-xxxx-yyyy"],
        )

        assert finding.severity == "critical"
        assert finding.cvss_score == 9.8
        assert finding.references == ["https://nvd.nist.gov/vuln/detail/CVE-2024-1234"]
        assert finding.aliases == ["GHSA-xxxx-yyyy"]

    def test_to_dict_excludes_none_values(self) -> None:
        """Test that to_dict excludes None values for cleaner JSON."""
        finding = Finding(
            id="test:finding",
            title="Test Finding",
            description="A test finding",
        )

        result = finding.to_dict()

        assert "id" in result
        assert "title" in result
        assert "description" in result
        assert "severity" in result  # has default value
        assert "status" not in result  # None, should be excluded
        assert "cvss_score" not in result  # None, should be excluded


class TestAssessmentSummary:
    """Tests for AssessmentSummary dataclass."""

    def test_create_compliance_summary(self) -> None:
        """Test creating a compliance-style summary."""
        summary = AssessmentSummary(
            total_findings=10,
            pass_count=7,
            fail_count=2,
            warning_count=1,
        )

        assert summary.total_findings == 10
        assert summary.pass_count == 7
        assert summary.fail_count == 2
        assert summary.warning_count == 1
        assert summary.error_count == 0  # default

    def test_create_security_summary(self) -> None:
        """Test creating a security-style summary with severity counts."""
        summary = AssessmentSummary(
            total_findings=15,
            by_severity={
                "critical": 1,
                "high": 3,
                "medium": 5,
                "low": 6,
            },
        )

        assert summary.total_findings == 15
        assert summary.by_severity["critical"] == 1
        assert summary.by_severity["high"] == 3

    def test_to_dict_excludes_none_values(self) -> None:
        """Test that to_dict excludes None values."""
        summary = AssessmentSummary(total_findings=5, pass_count=5)

        result = summary.to_dict()

        assert "total_findings" in result
        assert "pass_count" in result
        assert "by_severity" not in result  # None, should be excluded


class TestAssessmentResult:
    """Tests for AssessmentResult dataclass."""

    def test_create_result(self) -> None:
        """Test creating an AssessmentResult."""
        summary = AssessmentSummary(total_findings=1, pass_count=1)
        finding = Finding(
            id="test:finding",
            title="Test",
            description="Test finding",
            status="pass",
        )

        result = AssessmentResult(
            plugin_name="test-plugin",
            plugin_version="1.0.0",
            category="compliance",
            assessed_at="2024-01-15T12:00:00Z",
            summary=summary,
            findings=[finding],
        )

        assert result.plugin_name == "test-plugin"
        assert result.plugin_version == "1.0.0"
        assert result.category == "compliance"
        assert result.schema_version == "1.0"  # default
        assert len(result.findings) == 1

    def test_to_dict(self) -> None:
        """Test converting AssessmentResult to dictionary."""
        summary = AssessmentSummary(total_findings=1, pass_count=1)
        finding = Finding(
            id="test:finding",
            title="Test",
            description="Test finding",
            status="pass",
        )

        result = AssessmentResult(
            plugin_name="test-plugin",
            plugin_version="1.0.0",
            category="compliance",
            assessed_at="2024-01-15T12:00:00Z",
            summary=summary,
            findings=[finding],
            metadata={"key": "value"},
        )

        data = result.to_dict()

        assert data["schema_version"] == "1.0"
        assert data["plugin_name"] == "test-plugin"
        assert data["plugin_version"] == "1.0.0"
        assert data["category"] == "compliance"
        assert data["assessed_at"] == "2024-01-15T12:00:00Z"
        assert data["summary"]["total_findings"] == 1
        assert len(data["findings"]) == 1
        assert data["findings"][0]["id"] == "test:finding"
        assert data["metadata"] == {"key": "value"}


class TestAssessmentPlugin:
    """Tests for AssessmentPlugin abstract base class."""

    def test_cannot_instantiate_abstract_class(self) -> None:
        """Test that AssessmentPlugin cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AssessmentPlugin()  # type: ignore

    def test_concrete_plugin_implementation(self) -> None:
        """Test implementing a concrete plugin."""

        class TestPlugin(AssessmentPlugin):
            def get_metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="test",
                    version="1.0.0",
                    category=AssessmentCategory.COMPLIANCE,
                )

            def assess(self, sbom_id: str, sbom_path: Path) -> AssessmentResult:
                return AssessmentResult(
                    plugin_name="test",
                    plugin_version="1.0.0",
                    category="compliance",
                    assessed_at=datetime.now(timezone.utc).isoformat(),
                    summary=AssessmentSummary(total_findings=0),
                )

        plugin = TestPlugin()
        metadata = plugin.get_metadata()

        assert metadata.name == "test"
        assert metadata.version == "1.0.0"
        assert metadata.category == AssessmentCategory.COMPLIANCE

    def test_plugin_with_config(self) -> None:
        """Test that plugins receive configuration."""

        class ConfigurablePlugin(AssessmentPlugin):
            def get_metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="configurable",
                    version="1.0.0",
                    category=AssessmentCategory.LICENSE,
                )

            def assess(self, sbom_id: str, sbom_path: Path) -> AssessmentResult:
                return AssessmentResult(
                    plugin_name="configurable",
                    plugin_version="1.0.0",
                    category="license",
                    assessed_at=datetime.now(timezone.utc).isoformat(),
                    summary=AssessmentSummary(total_findings=0),
                    metadata={"config": self.config},
                )

        config = {"allowed_licenses": ["MIT", "Apache-2.0"]}
        plugin = ConfigurablePlugin(config=config)

        assert plugin.config == config

    def test_plugin_default_config(self) -> None:
        """Test that plugins have empty config by default."""

        class SimplePlugin(AssessmentPlugin):
            def get_metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="simple",
                    version="1.0.0",
                    category=AssessmentCategory.COMPLIANCE,
                )

            def assess(self, sbom_id: str, sbom_path: Path) -> AssessmentResult:
                return AssessmentResult(
                    plugin_name="simple",
                    plugin_version="1.0.0",
                    category="compliance",
                    assessed_at=datetime.now(timezone.utc).isoformat(),
                    summary=AssessmentSummary(total_findings=0),
                )

        plugin = SimplePlugin()

        assert plugin.config == {}


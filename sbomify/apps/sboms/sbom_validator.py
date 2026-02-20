from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from .sbom_base_validator import SBOMSchemaError, SBOMValidator, SBOMVersionError
from .schemas import BaseLicenseSchema, SBOMFormat


class SPDXValidator(SBOMValidator):
    """SPDX SBOM validator."""

    def _validate_version(self) -> None:
        """Validate that the version is supported."""
        supported_versions = ["2.2", "2.3", "3.0"]
        # Normalize 3.0.x patch versions to "3.0" and reject other 3.* minors
        normalized = self.version
        if normalized.startswith("3."):
            if normalized == "3.0" or normalized.startswith("3.0."):
                normalized = "3.0"
            else:
                raise SBOMVersionError(f"Unsupported SPDX version: {self.version}")
        if normalized not in supported_versions:
            raise SBOMVersionError(f"Unsupported SPDX version: {self.version}")

    def _is_spdx3_context(self, sbom_data: Dict[str, Any]) -> bool:
        """Check if SBOM data has an @context indicating SPDX 3.0."""
        context = sbom_data.get("@context", "")
        if isinstance(context, str):
            return "spdx.org/rdf/3.0" in context
        if isinstance(context, list):
            return any("spdx.org/rdf/3.0" in str(c) for c in context)
        return False

    def validate(self, sbom_data: Dict[str, Any]) -> BaseModel:
        """Validate SPDX SBOM data."""
        self.validate_version_specific_requirements(sbom_data)
        try:
            if self.version.startswith("3."):
                from .schemas import SPDX3Schema

                return SPDX3Schema.model_validate(sbom_data)
            else:
                from .schemas import SPDXSchema

                return SPDXSchema(**sbom_data)
        except PydanticValidationError as e:
            raise SBOMSchemaError(f"SPDX schema validation failed: {str(e)}")

    def validate_version_specific_requirements(self, sbom_data: Dict[str, Any]) -> None:
        """Validate SPDX version-specific requirements."""
        if self.version.startswith("3."):
            # SPDX 3.x: accept @context-based (spec-compliant) or spdxVersion-based (legacy)
            has_context = self._is_spdx3_context(sbom_data)
            actual_version = sbom_data.get("spdxVersion", "")
            if not has_context and not actual_version.startswith("SPDX-3."):
                raise SBOMSchemaError(
                    f"SPDX version mismatch: expected @context with spdx.org/rdf/3.0 or "
                    f"spdxVersion starting with SPDX-3., got {actual_version}"
                )
        else:
            actual_version = sbom_data.get("spdxVersion", "")
            if actual_version != f"SPDX-{self.version}":
                raise SBOMSchemaError(f"SPDX version mismatch: expected SPDX-{self.version}, got {actual_version}")

    def get_version_specific_fields(self) -> Dict[str, List[str]]:
        """Get required and optional fields for SPDX version."""
        if self.version.startswith("3."):
            # SPDX 3.0: spec-compliant uses @context/@graph, legacy uses spdxVersion/elements
            # At least one of these pairs must be present
            required_fields: List[str] = []
            optional_fields = [
                "@context",
                "@graph",
                "spdxVersion",
                "elements",
                "creationInfo",
                "name",
                "spdxId",
                "rootElement",
                "dataLicense",
            ]
            return {"required": required_fields, "optional": optional_fields}

        required_fields = ["SPDXID", "creationInfo", "dataLicense", "name", "spdxVersion"]
        optional_fields = ["packages", "relationships", "annotations"]

        if self.version >= "2.3":
            required_fields.extend(["documentNamespace"])
            optional_fields.extend(["snippets", "extractedLicensingInfo"])

        return {"required": required_fields, "optional": optional_fields}

    def validate_license(self, license_data: Dict[str, Any]) -> BaseLicenseSchema:
        """Validate and convert license data to our schema."""
        try:
            from .schemas import CustomLicenseSchema

            if "licenseId" in license_data:
                # For now, return a basic schema since LicenseSchema isn't defined
                return BaseLicenseSchema()
            elif "name" in license_data:
                return CustomLicenseSchema(name=license_data["name"])
            else:
                raise SBOMSchemaError("License data must contain either licenseId or name")
        except PydanticValidationError as e:
            raise SBOMSchemaError(f"License validation failed: {str(e)}")


def get_validator(sbom_format: SBOMFormat, version: str) -> SBOMValidator:
    """Get the appropriate validator for the given SBOM format and version."""
    if sbom_format == SBOMFormat.cyclonedx:
        from .cyclonedx_validator import CycloneDXValidator

        return CycloneDXValidator(version)
    elif sbom_format == SBOMFormat.spdx:
        return SPDXValidator(version)
    else:
        raise ValueError(f"Unsupported SBOM format: {sbom_format}")

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
        if self.version not in supported_versions:
            raise SBOMVersionError(f"Unsupported SPDX version: {self.version}")

    def validate(self, sbom_data: Dict[str, Any]) -> BaseModel:
        """Validate SPDX SBOM data."""
        self.validate_version_specific_requirements(sbom_data)
        try:
            from .schemas import SPDXSchema

            return SPDXSchema(**sbom_data)
        except PydanticValidationError as e:
            raise SBOMSchemaError(f"SPDX schema validation failed: {str(e)}")

    def validate_version_specific_requirements(self, sbom_data: Dict[str, Any]) -> None:
        """Validate SPDX version-specific requirements."""
        if sbom_data.get("spdxVersion") != f"SPDX-{self.version}":
            raise SBOMSchemaError(
                f"SPDX version mismatch: expected SPDX-{self.version}, got {sbom_data.get('spdxVersion')}"
            )

    def get_version_specific_fields(self) -> Dict[str, List[str]]:
        """Get required and optional fields for SPDX version."""
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

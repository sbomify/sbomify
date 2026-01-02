from __future__ import annotations

import logging
from typing import Any, Dict

from pydantic import BaseModel, ValidationError

from .sbom_base_validator import SBOMSchemaError, SBOMValidator, SBOMVersionError
from .sbom_format_schemas import cyclonedx_1_3 as cdx13
from .sbom_format_schemas import cyclonedx_1_4 as cdx14
from .sbom_format_schemas import cyclonedx_1_5 as cdx15
from .sbom_format_schemas import cyclonedx_1_6 as cdx16
from .schemas import BaseLicenseSchema, CustomLicenseSchema, LicenseSchema

log = logging.getLogger("sbomify.cyclonedx_validator")


class CycloneDXValidationError(Exception):
    """Base exception for CycloneDX validation errors."""

    pass


class CycloneDXVersionError(CycloneDXValidationError):
    """Exception raised when there's a version mismatch or unsupported version."""

    pass


class CycloneDXSchemaError(CycloneDXValidationError):
    """Exception raised when there's a schema validation error."""

    pass


class CycloneDXValidator(SBOMValidator):
    """Validator for CycloneDX SBOMs."""

    def __init__(self, version: str):
        """Initialize CycloneDX validator.

        Args:
            version: The CycloneDX version to validate against
        """
        self.version = version
        self._validate_version()
        self._version_map = {
            "1.3": cdx13.CyclonedxSoftwareBillOfMaterialsStandard,
            "1.4": cdx14.CyclonedxSoftwareBillOfMaterialsStandard,
            "1.5": cdx15.CyclonedxSoftwareBillOfMaterialsStandard,
            "1.6": cdx16.CyclonedxSoftwareBillOfMaterialsStandard,
        }

    def _validate_version(self) -> None:
        """Validate that the version is supported."""
        supported_versions = ["1.3", "1.4", "1.5", "1.6"]
        if self.version not in supported_versions:
            raise SBOMVersionError(f"Unsupported CycloneDX version: {self.version}")

    def validate(self, sbom_data: Dict[str, Any]) -> BaseModel:
        """Validate CycloneDX SBOM data.

        Args:
            sbom_data: The CycloneDX SBOM data to validate

        Returns:
            The validated CycloneDX model

        Raises:
            SBOMValidationError: If validation fails
        """
        try:
            schema_class = self._version_map[self.version]
            log.debug(f"Validating CycloneDX {self.version} data against schema {schema_class.__name__}")
            return schema_class(**sbom_data)
        except ValidationError as e:
            log.error(f"CycloneDX schema validation failed for version {self.version}: {str(e)}")
            log.error(f"Validation errors: {e.errors()}")
            log.error(f"Failed data: {sbom_data}")
            raise SBOMSchemaError(f"CycloneDX schema validation failed: {str(e)}")

    def get_version_specific_fields(self) -> Dict[str, list[str]]:
        """Get required and optional fields for CycloneDX version.

        Returns:
            Dict containing 'required' and 'optional' field lists
        """
        required_fields = ["specVersion", "bomFormat", "metadata"]
        optional_fields = ["components", "services", "dependencies", "compositions", "vulnerabilities"]

        if self.version == "1.6":
            # Note: "version" is not actually required in CycloneDX 1.6 spec
            optional_fields.extend(["formulation", "lifecycles"])

        return {"required": required_fields, "optional": optional_fields}

    def validate_version_specific_requirements(self, sbom_data: Dict[str, Any]) -> None:
        """Validate CycloneDX version-specific requirements.

        Args:
            sbom_data: The CycloneDX SBOM data to validate

        Raises:
            SBOMValidationError: If validation fails
        """
        log.debug(f"Validating version-specific requirements for CycloneDX {self.version}")

        # Check required fields first
        required_fields = self.get_version_specific_fields()["required"]
        for field in required_fields:
            if field not in sbom_data:
                error_msg = f"Missing required field: {field}"
                log.error(error_msg)
                log.error(f"Available fields: {list(sbom_data.keys())}")
                raise SBOMSchemaError(error_msg)

        # Check version matches
        if sbom_data.get("specVersion") != self.version:
            error_msg = f"CycloneDX version mismatch: expected {self.version}, got {sbom_data.get('specVersion')}"
            log.error(error_msg)
            raise SBOMSchemaError(error_msg)

        # Check format
        if sbom_data.get("bomFormat") != "CycloneDX":
            error_msg = f"Invalid bomFormat: expected 'CycloneDX', got {sbom_data.get('bomFormat')}"
            log.error(error_msg)
            raise SBOMSchemaError(error_msg)

    def validate_license(self, license_data: Dict[str, Any]) -> BaseLicenseSchema:
        """Validate and convert license data to our schema.

        Args:
            license_data: The license data to validate

        Returns:
            A validated license schema

        Raises:
            SBOMSchemaError: If validation fails
        """
        try:
            if "id" in license_data:
                return LicenseSchema(id=license_data["id"])
            elif "name" in license_data:
                return CustomLicenseSchema(name=license_data["name"])
            else:
                raise SBOMSchemaError("License data must contain either id or name")
        except ValidationError as e:
            raise SBOMSchemaError(f"License validation failed: {str(e)}")

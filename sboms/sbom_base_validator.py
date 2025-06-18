from abc import ABC, abstractmethod
from typing import Any, Dict

from pydantic import BaseModel


class SBOMValidationError(Exception):
    """Base exception for SBOM validation errors."""

    pass


class SBOMVersionError(SBOMValidationError):
    """Exception raised when SBOM version is not supported."""

    pass


class SBOMSchemaError(SBOMValidationError):
    """Exception raised when SBOM schema validation fails."""

    pass


class SBOMValidator(ABC):
    """Abstract base class for SBOM validators."""

    def __init__(self, version: str):
        self.version = version
        self._validate_version()

    @abstractmethod
    def _validate_version(self) -> None:
        """Validate that the version is supported."""
        pass

    @abstractmethod
    def validate(self, sbom_data: Dict[str, Any]) -> BaseModel:
        """Validate SBOM data and return validated model."""
        pass

    @abstractmethod
    def get_version_specific_fields(self) -> Dict[str, list[str]]:
        """Get required and optional fields for this SBOM version."""
        pass

    @abstractmethod
    def validate_version_specific_requirements(self, sbom_data: Dict[str, Any]) -> None:
        """Validate version-specific requirements."""
        pass

from enum import Enum


class CycloneDXSupportedVersion(str, Enum):
    """Supported CycloneDX versions."""

    v1_5 = "1.5"
    v1_6 = "1.6"
    v1_7 = "1.7"

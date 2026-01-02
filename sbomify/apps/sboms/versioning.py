from enum import Enum


class CycloneDXSupportedVersion(str, Enum):
    """Supported CycloneDX versions."""

    v1_3 = "1.3"
    v1_4 = "1.4"
    v1_5 = "1.5"
    v1_6 = "1.6"
    v1_7 = "1.7"

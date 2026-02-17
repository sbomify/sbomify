"""
TEA (Transparency Exchange API) Pydantic schemas.

Based on TEA OpenAPI Spec v0.3.0-beta.2:
https://raw.githubusercontent.com/CycloneDX/transparency-exchange-api/refs/heads/main/spec/openapi.yaml

Note: Identifier types use `str` (not Literal) because sbomify extends the spec
with GTIN and ASIN types beyond the official CPE, TEI, PURL enum.
All other enum fields use Literal types matching the spec exactly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# Custom datetime type that serializes to UTC with Z suffix (spec requirement).
# Spec pattern: ^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$
TEADateTime = Annotated[
    datetime,
    PlainSerializer(
        lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        return_type=str,
    ),
]

# Spec enum types
ArtifactType = Literal[
    "ATTESTATION",
    "BOM",
    "BUILD_META",
    "CERTIFICATION",
    "FORMULATION",
    "LICENSE",
    "RELEASE_NOTES",
    "SECURITY_TXT",
    "THREAT_MODEL",
    "VULNERABILITIES",
    "OTHER",
]

ChecksumType = Literal[
    "MD5",
    "SHA-1",
    "SHA-256",
    "SHA-384",
    "SHA-512",
    "SHA3-256",
    "SHA3-384",
    "SHA3-512",
    "BLAKE2b-256",
    "BLAKE2b-384",
    "BLAKE2b-512",
    "BLAKE3",
]

UpdateReasonType = Literal[
    "INITIAL_RELEASE",
    "VEX_UPDATED",
    "ARTIFACT_UPDATED",
    "ARTIFACT_ADDED",
    "ARTIFACT_REMOVED",
]

# =============================================================================
# Core Schemas
# =============================================================================


class TEAIdentifier(BaseModel):
    """An identifier with a specified type."""

    model_config = ConfigDict(extra="forbid")

    idType: str = Field(..., description="Type of identifier, e.g. TEI, PURL, CPE")
    idValue: str = Field(..., description="Identifier value")


class TEAChecksum(BaseModel):
    """Checksum information."""

    model_config = ConfigDict(extra="forbid")

    algType: ChecksumType = Field(..., description="Checksum algorithm")
    algValue: str = Field(..., description="Checksum value")


# =============================================================================
# Product Schemas
# =============================================================================


class TEAProduct(BaseModel):
    """A TEA product."""

    uuid: str = Field(..., description="A unique identifier for the TEA product")
    name: str = Field(..., description="Product name")
    identifiers: list[TEAIdentifier] = Field(..., description="List of identifiers for the product")


class TEAComponentRef(BaseModel):
    """A reference to a TEA component or specific component release."""

    uuid: str = Field(..., description="A unique identifier for the TEA component")
    release: str | None = Field(None, description="Optional UUID of a specific release")


class TEAProductRelease(BaseModel):
    """A specific release of a TEA product."""

    uuid: str = Field(..., description="A unique identifier for the TEA Product Release")
    product: str | None = Field(None, description="UUID of the TEA Product this release belongs to")
    productName: str | None = Field(None, description="Name of the TEA Product this release belongs to")
    version: str = Field(..., description="Version number of the product release")
    createdDate: TEADateTime = Field(..., description="Timestamp when this Product Release was created in TEA")
    releaseDate: TEADateTime | None = Field(None, description="Timestamp of the product release")
    preRelease: bool = Field(False, description="A flag indicating pre-release status")
    identifiers: list[TEAIdentifier] = Field(default_factory=list, description="List of identifiers")
    components: list[TEAComponentRef] = Field(..., description="List of component references")


# =============================================================================
# Component Schemas
# =============================================================================


class TEAComponent(BaseModel):
    """A TEA component."""

    uuid: str = Field(..., description="A unique identifier for the TEA component")
    name: str = Field(..., description="Component name")
    identifiers: list[TEAIdentifier] = Field(..., description="List of identifiers for the component")


class TEAReleaseDistribution(BaseModel):
    """Distribution information for a component release."""

    distributionType: str = Field(..., description="Unique identifier for the distribution type")
    description: str | None = Field(None, description="Free-text description of the distribution")
    identifiers: list[TEAIdentifier] = Field(default_factory=list, description="List of identifiers")
    url: str | None = Field(None, description="Direct download URL for the distribution")
    signatureUrl: str | None = Field(None, description="Direct download URL for the external signature")
    checksums: list[TEAChecksum] = Field(default_factory=list, description="List of checksums")


class TEARelease(BaseModel):
    """A TEA Component Release."""

    uuid: str = Field(..., description="A unique identifier for the TEA Component Release")
    component: str | None = Field(None, description="UUID of the TEA Component this release belongs to")
    componentName: str | None = Field(None, description="Name of the TEA Component")
    version: str = Field(..., description="Version number")
    createdDate: TEADateTime = Field(..., description="Timestamp when this Release was created in TEA")
    releaseDate: TEADateTime | None = Field(None, description="Timestamp of the release")
    preRelease: bool = Field(False, description="A flag indicating pre-release status")
    identifiers: list[TEAIdentifier] = Field(default_factory=list, description="List of identifiers")
    distributions: list[TEAReleaseDistribution] = Field(default_factory=list, description="List of distributions")


# =============================================================================
# Collection and Artifact Schemas
# =============================================================================


class TEAArtifactFormat(BaseModel):
    """A security-related document in a specific format."""

    mediaType: str = Field(..., description="The MIME type of the document")
    description: str | None = Field(None, description="A free text describing the TEA Artifact")
    url: str = Field(..., description="Direct download URL for the TEA Artifact")
    signatureUrl: str | None = Field(None, description="Direct download URL for an external signature")
    checksums: list[TEAChecksum] = Field(default_factory=list, description="List of checksums")


class TEAArtifact(BaseModel):
    """A security-related document."""

    uuid: str = Field(..., description="UUID of the TEA Artifact object")
    name: str = Field(..., description="Name of TEA Artifact")
    type: ArtifactType = Field(..., description="Type of TEA Artifact")
    distributionTypes: list[str] | None = Field(
        None, description="List of component distribution types this applies to"
    )
    formats: list[TEAArtifactFormat] = Field(..., description="List of formats for this artifact")


class TEACollectionUpdateReason(BaseModel):
    """Reason for the update to the TEA collection."""

    type: UpdateReasonType = Field(..., description="Type of update reason")
    comment: str | None = Field(None, description="Free text description")


class TEACollection(BaseModel):
    """A collection of security-related documents."""

    uuid: str = Field(..., description="UUID of the TEA Collection object")
    version: int = Field(..., description="TEA Collection version")
    date: TEADateTime = Field(..., description="The date when the TEA Collection version was created")
    belongsTo: Literal["COMPONENT_RELEASE", "PRODUCT_RELEASE"] = Field(
        ..., description="Indicates whether this collection belongs to a Component Release or Product Release"
    )
    updateReason: TEACollectionUpdateReason | None = Field(None, description="Reason for the update/release")
    artifacts: list[TEAArtifact] = Field(default_factory=list, description="List of TEA Artifact objects")


class TEAComponentReleaseWithCollection(BaseModel):
    """A TEA Component Release combined with its latest collection."""

    release: TEARelease = Field(..., description="The TEA Component Release information")
    latestCollection: TEACollection = Field(..., description="The latest TEA Collection for this component release")


# =============================================================================
# Discovery Schemas
# =============================================================================


class TEAServerInfo(BaseModel):
    """TEA server information including URL, versions, and optional priority."""

    model_config = ConfigDict(extra="forbid")

    rootUrl: str = Field(..., description="Root URL of the TEA server without trailing slash")
    versions: list[str] = Field(..., min_length=1, description="Supported TEA API versions at this server")
    priority: float = Field(1.0, ge=0.0, le=1.0, description="Optional priority for this server")


class TEADiscoveryInfo(BaseModel):
    """Discovery information for a TEI."""

    model_config = ConfigDict(extra="forbid")

    productReleaseUuid: str = Field(..., description="UUID of the resolved TEA Product Release")
    servers: list[TEAServerInfo] = Field(..., min_length=1, description="Array of TEA server information")


# =============================================================================
# Well-Known Schema
# =============================================================================


class TEAWellKnownEndpoint(BaseModel):
    """TEA endpoint information for .well-known/tea."""

    url: str = Field(..., description="Base URL of the TEA API endpoint (no trailing slash)")
    versions: list[str] = Field(..., min_length=1, description="Supported TEA API versions for this endpoint")
    priority: float = Field(1.0, ge=0.0, le=1.0, description="Optional priority for this endpoint")


class TEAWellKnownResponse(BaseModel):
    """TEA .well-known discovery document."""

    schemaVersion: int = Field(1, description="Schema version for the TEA .well-known discovery document")
    endpoints: list[TEAWellKnownEndpoint] = Field(
        ..., min_length=1, description="List of available TEA service endpoints"
    )


# =============================================================================
# Pagination Schemas
# =============================================================================


class TEAPaginationDetails(BaseModel):
    """Pagination metadata."""

    timestamp: TEADateTime = Field(..., description="Timestamp of the response")
    pageStartIndex: int = Field(0, description="Page start index")
    pageSize: int = Field(100, description="Page size")
    totalResults: int = Field(..., description="Total number of results")


class TEAPaginatedProductResponse(TEAPaginationDetails):
    """A paginated response containing TEA Products."""

    results: list[TEAProduct] = Field(default_factory=list, description="List of TEA Products")


class TEAPaginatedProductReleaseResponse(TEAPaginationDetails):
    """A paginated response containing TEA Product Releases."""

    results: list[TEAProductRelease] = Field(default_factory=list, description="List of TEA Product Releases")


# =============================================================================
# Error Schemas
# =============================================================================


class TEAErrorResponse(BaseModel):
    """Error response matching TEA spec error-response schema."""

    model_config = ConfigDict(extra="forbid")

    error: Literal["OBJECT_UNKNOWN", "OBJECT_NOT_SHAREABLE"] = Field(..., description="Error classification")


class TEABadRequestResponse(BaseModel):
    """Bad request error response for 400 status codes."""

    model_config = ConfigDict(extra="forbid")

    error: str = Field(..., description="Error message describing why the request failed")

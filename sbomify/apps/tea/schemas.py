"""TEA schemas — re-exported from libtea with server-side aliases."""

from libtea.models import (
    CLE as TEACLE,
)
from libtea.models import (
    Artifact as TEAArtifact,
)
from libtea.models import (
    ArtifactFormat as TEAArtifactFormat,
)
from libtea.models import (
    Checksum as TEAChecksum,
)
from libtea.models import (
    Collection as TEACollection,
)
from libtea.models import (
    CollectionUpdateReason as TEACollectionUpdateReason,
)
from libtea.models import (
    Component as TEAComponent,
)
from libtea.models import (
    ComponentRef as TEAComponentRef,
)
from libtea.models import (
    ComponentReleaseWithCollection as TEAComponentReleaseWithCollection,
)
from libtea.models import (
    DiscoveryInfo as TEADiscoveryInfo,
)
from libtea.models import (
    ErrorResponse as TEAErrorResponse,
)
from libtea.models import (
    Identifier as TEAIdentifier,
)
from libtea.models import (
    PaginatedProductReleaseResponse as TEAPaginatedProductReleaseResponse,
)
from libtea.models import (
    PaginatedProductResponse as TEAPaginatedProductResponse,
)
from libtea.models import (
    Product as TEAProduct,
)
from libtea.models import (
    ProductRelease as TEAProductRelease,
)
from libtea.models import (
    Release as TEARelease,
)
from libtea.models import (
    ReleaseDistribution as TEAReleaseDistribution,
)
from libtea.models import (
    TeaEndpoint as TEAWellKnownEndpoint,
)
from libtea.models import (
    TeaServerInfo as TEAServerInfo,
)
from libtea.models import (
    TeaWellKnown as TEAWellKnownResponse,
)
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "TEAArtifact",
    "TEACLE",
    "TEAArtifactFormat",
    "TEABadRequestResponse",
    "TEAChecksum",
    "TEACollection",
    "TEACollectionUpdateReason",
    "TEAComponent",
    "TEAComponentRef",
    "TEAComponentReleaseWithCollection",
    "TEADiscoveryInfo",
    "TEAErrorResponse",
    "TEAIdentifier",
    "TEAPaginatedProductReleaseResponse",
    "TEAPaginatedProductResponse",
    "TEAProduct",
    "TEAProductRelease",
    "TEARelease",
    "TEAReleaseDistribution",
    "TEAServerInfo",
    "TEAWellKnownEndpoint",
    "TEAWellKnownResponse",
]


class TEABadRequestResponse(BaseModel):
    """Bad request error response for 400 status codes (sbomify-specific, no libtea equivalent)."""

    model_config = ConfigDict(extra="forbid")

    error: str = Field(..., description="Error message describing why the request failed")

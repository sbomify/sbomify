"""Wire shapes for the advisories API.

Deliberately a subset of what the service projections carry. Those are built
for the pages and include presentation (a badge variant, an icon name, a
pre-formatted date), and none of that belongs in a contract a client writes
against. The names here follow the model rather than the templates, so
``status`` is the publication state the model calls ``status`` and the fix's
progress is ``remediation_status``.

Two families. The workspace shapes carry the record as its owners see it,
drafts and internal history included. The public shapes carry what a
trust-center reader may be told, which the trust-center service has already
decided before anything here is built.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ninja import Schema
from pydantic import ConfigDict, Field

from sbomify.apps.core.schemas import PaginationMeta


class AdvisoryProductSchema(Schema):
    """A product an advisory names.

    ``id`` is null when the advisory names a product this workspace does not
    track, or tracked and has since deleted; the name is kept either way.
    """

    id: str | None = None
    name: str
    affected_ranges: list[str] = Field(default_factory=list)


class AdvisoryVulnerabilitySchema(Schema):
    id: str
    cve_id: str = ""
    title: str = ""
    description: str = ""
    severity: str = ""
    cwe_ids: list[str] = Field(default_factory=list)
    cvss_scores: list[dict[str, Any]] = Field(default_factory=list)
    exploitation_status: str = ""
    recommendation: str = ""


class AdvisoryReferenceSchema(Schema):
    id: str
    type: str = ""
    external_id: str = ""
    url: str = ""
    summary: str = ""
    category: str = ""


class AdvisoryEventSchema(Schema):
    """One entry in the advisory's append-only history."""

    id: str
    kind: str
    body: str = ""
    actor: str = ""
    channel: str = Field(
        "",
        description="How the change was sent: agent (an AI agent token), api (any other token), ci, "
        "or blank for a change made in the app.",
    )
    token_id: str = Field("", description="The API token that made the change, when one did.")
    from_status: str | None = None
    to_status: str | None = None
    created_at: datetime


class AdvisoryStatusSchema(Schema):
    """What one vulnerability means for one product: the row the trust center and CSAF read."""

    id: str
    label: str = Field(description="The product, and the vulnerability when the advisory has several.")
    product: str
    product_id: str | None = Field(None, description="The sbomify product, when the row names one.")
    vulnerability: str
    vulnerability_id: str
    status: str = Field(description="exploitable, not_affected, false_positive, in_triage or resolved.")
    justification: str = ""
    response: str = ""
    impact_statement: str = ""
    action_statement: str = ""
    recommended_version: str = ""
    recommended_release_id: str | None = None
    fixed_version: str = Field("", description="The first version carrying the fix.")
    fixed_release_id: str | None = None
    affected_versions: list[str] = Field(default_factory=list)


class AdvisorySchema(Schema):
    id: str
    tracking_id: str = Field(
        "", description="The workspace's own identifier, allocated at publication. Empty while a draft."
    )
    title: str
    summary: str = ""
    description: str = ""
    advisory_type: str
    severity: str = ""
    cvss_score: float | None = None
    cvss_vector: str = ""
    status: str = Field(description="Publication state: draft, published or withdrawn.")
    remediation_status: str = Field(description="Where the fix is, which is not whether it is published.")
    is_open: bool
    visibility: str
    vulnerability_count: int = 0
    vulnerability_id: str = Field("", description="The first CVE the advisory cites, when it cites one.")
    products: list[AdvisoryProductSchema] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    withdrawn_at: datetime | None = None
    withdrawal_reason: str = ""


class AdvisoryDetailSchema(AdvisorySchema):
    vulnerabilities: list[AdvisoryVulnerabilitySchema] = Field(default_factory=list)
    statuses: list[AdvisoryStatusSchema] = Field(default_factory=list)
    references: list[AdvisoryReferenceSchema] = Field(default_factory=list)
    timeline: list[AdvisoryEventSchema] = Field(default_factory=list)


class CreateAdvisorySchema(Schema):
    title: str = Field(min_length=1, max_length=255)
    severity: str = ""
    description: str = ""
    identifier: str = Field("", description="A CVE or other identifier the advisory is about.")
    remediation_status: str = ""
    cvss_score: float | None = None
    cvss_vector: str = ""
    product_ids: list[str] = Field(default_factory=list)
    affected_release_ids: list[str] = Field(
        default_factory=list,
        description="Releases of the named products that carry the vulnerability; each becomes an affected version.",
    )


class UpdateAdvisorySchema(Schema):
    """A partial update: a field left out keeps its stored value.

    ``cvss_score`` and ``cvss_vector`` are one entry: sending ``cvss_score``
    as null clears both, and a vector without a score is refused. A field this
    endpoint does not write is a 422, not a 200 that stored nothing.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, min_length=1, max_length=255)
    severity: str | None = None
    description: str | None = None
    summary: str | None = Field(None, description="The one-paragraph summary the trust center leads with.")
    cvss_score: float | None = None
    cvss_vector: str | None = None


class ProductStatusUpdateSchema(Schema):
    """A partial update of a product status: only the fields sent are written.

    ``fixed_version`` or ``fixed_release_id`` records the first version carrying
    the fix, which is what the trust center and CSAF list as fixed. Unless a
    recommendation is sent too, it also becomes what users are told to upgrade
    to. Send an empty string or null to clear one.
    """

    model_config = ConfigDict(extra="forbid")

    status: str | None = Field(None, description="exploitable, not_affected, false_positive, in_triage or resolved.")
    justification: str | None = Field(None, description="Why a not_affected product is not affected.")
    response: str | None = Field(
        None, description="can_not_fix, will_not_fix, update, rollback or workaround_available."
    )
    impact_statement: str | None = None
    action_statement: str | None = Field(None, description="What users should do. Shown to readers.")
    recommended_version: str | None = None
    recommended_release_id: str | None = Field(None, description="A release of this product. Not the floating latest.")
    fixed_version: str | None = None
    fixed_release_id: str | None = Field(None, description="A release of this product. Not the floating latest.")


class AddAdvisoryProductSchema(ProductStatusUpdateSchema):
    """Name another product on an advisory, or more of its affected releases.

    The status fields apply to the new product's rows. Without them it starts
    under investigation, which a resolved advisory refuses.
    """

    product_id: str
    affected_release_ids: list[str] = Field(
        default_factory=list, description="Releases of this product that carry the vulnerability."
    )


class PublishAdvisorySchema(Schema):
    """Publication moves both axes at once: a draft nobody can read becomes a
    published advisory with the visibility asked for here."""

    visibility: str = Field(description="The visibility to disclose at.")


class AdvisoryUpdateSchema(Schema):
    """One timeline entry: a note, or a remediation status move with commentary."""

    kind: str = Field(
        description="'update' for a note that moves nothing, or a remediation status: "
        "identified, investigating, fix_in_progress, resolved, wont_fix."
    )
    note: str = Field(
        "",
        description="Markdown. Headings, lists, bold, italic, code spans and http(s) or mailto links are rendered; "
        "raw HTML is shown as text.",
    )


class WithdrawAdvisorySchema(Schema):
    reason: str = Field(min_length=1, description="Why the advisory is withdrawn. Shown to readers.")


class PublicAdvisoryProductSchema(Schema):
    """A product the reader is allowed to see named."""

    id: str | None = None
    name: str


class PublicAdvisoryStatusSchema(Schema):
    """What one vulnerability means for one product, as a reader may see it."""

    id: str
    vulnerability: str
    product: str
    product_id: str | None = None
    status: str
    justification: str = ""
    impact_statement: str = ""
    action_statement: str = ""
    response: str = ""
    recommended_version: str = ""
    affected: str = Field(
        "",
        description="Affected versions as a comparison, e.g. '>= 1.0, < 1.4.3'. Empty when no versions were "
        "recorded, or when status says the product is not affected at all.",
    )
    unaffected: str = Field("", description="Versions that are not affected, e.g. '>= 1.4.3'. Empty on the same terms.")
    version_ranges: list[str] = Field(default_factory=list)


class PublicAdvisoryEventSchema(Schema):
    id: str
    kind: str
    note: str = ""
    created_at: datetime


class PublicAdvisorySchema(Schema):
    id: str
    tracking_id: str = ""
    title: str
    summary: str = ""
    severity: str = ""
    cvss_score: float | None = None
    status: str = Field(description="Publication state: published or withdrawn.")
    remediation_status: str
    is_open: bool
    visibility: str
    is_withdrawn: bool = False
    withdrawal_reason: str = ""
    products: list[PublicAdvisoryProductSchema] = Field(default_factory=list)
    withheld_product_count: int = Field(0, description="Products the advisory names that this reader may not see.")
    vulnerability_count: int = 0
    cve_ids: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    updated_at: datetime | None = None


class PublicAdvisoryDetailSchema(PublicAdvisorySchema):
    description: str = ""
    vulnerabilities: list[AdvisoryVulnerabilitySchema] = Field(default_factory=list)
    references: list[AdvisoryReferenceSchema] = Field(default_factory=list)
    statuses: list[PublicAdvisoryStatusSchema] = Field(default_factory=list)
    timeline: list[PublicAdvisoryEventSchema] = Field(default_factory=list)
    acknowledgments: list[dict[str, Any]] = Field(default_factory=list)


class PublicAdvisoryListSchema(Schema):
    items: list[PublicAdvisorySchema]
    pagination: PaginationMeta
    hidden_count: int = Field(0, description="Advisories this reader may not see. Signing in may change it.")
    viewer_is_authenticated: bool = False
    viewer_has_gated_grant: bool = False

"""Who may read which advisory on the trust center.

Every test here is about the visibility rule, because that is the part where a
mistake discloses something. The projection's shape is checked only where a
leak would hide in it (internal comments, withheld product names).
"""

from __future__ import annotations

from urllib.parse import urlencode

import pytest
from django.http import HttpRequest, QueryDict
from django.utils import timezone

from sbomify.apps.core.models import Component, Product
from sbomify.apps.documents.access_models import AccessRequest
from sbomify.apps.security_advisories.models import (
    AdvisoryEvent,
    AdvisoryProduct,
    AdvisoryProductStatus,
    AdvisoryVersionRange,
    AdvisoryVulnerability,
    SecurityAdvisory,
)
from sbomify.apps.security_advisories.services.trust_center import (
    browse_public_advisories,
    get_public_advisory,
    list_public_advisories,
    parse_advisory_query,
    public_advisory_summary,
    resolve_viewer_scope,
)
from sbomify.apps.teams.models import Member

from .conftest import publish

pytestmark = pytest.mark.django_db


# --- helpers -----------------------------------------------------------------


class _AnonymousUser:
    is_authenticated = False


def make_request(user: object | None = None) -> HttpRequest:
    """A bare request carrying just a user, which is all the service reads."""
    request = HttpRequest()
    request.user = user or _AnonymousUser()  # type: ignore[assignment]
    request.session = {}  # type: ignore[assignment]
    return request


def listed_ids(request: HttpRequest, team: object) -> list[str]:
    payload = list_public_advisories(request, team).value or {}
    return [a["pk"] for a in payload["advisories"]]


@pytest.fixture
def public_product(team):
    """A product the trust center lists: public, with a public component."""
    product = Product.objects.create(name="Acme Gateway", team=team, is_public=True)
    component = Component.objects.create(
        name="gateway-core", team=team, visibility=Component.Visibility.PUBLIC
    )
    product.components.add(component)
    return product


@pytest.fixture
def gated_product(team):
    """Public product whose only component is gated — NDA holders only."""
    product = Product.objects.create(name="Acme Vault", team=team, is_public=True)
    component = Component.objects.create(
        name="vault-core", team=team, visibility=Component.Visibility.GATED
    )
    product.components.add(component)
    return product


@pytest.fixture
def unlisted_product(team):
    """A product the trust center never lists at all."""
    return Product.objects.create(name="Skunkworks", team=team, is_public=False)


def advisory_for(team, product, *, visibility: str, title: str = "Advisory") -> SecurityAdvisory:
    advisory = SecurityAdvisory.objects.create(team=team, title=title)
    AdvisoryProduct.objects.create(advisory=advisory, product=product)
    return publish(advisory, visibility=visibility)


def grant_gated_access(team, user) -> None:
    """An external customer approved for the workspace, with no NDA configured."""
    AccessRequest.objects.create(
        team=team, user=user, status=AccessRequest.Status.APPROVED, decided_at=timezone.now()
    )


# --- the three visibilities --------------------------------------------------


def test_private_advisory_is_never_listed(team, public_product, sample_user):
    """Not even to an owner: the trust center is the outside view."""
    advisory_for(team, public_product, visibility=SecurityAdvisory.Visibility.PRIVATE)
    assert listed_ids(make_request(sample_user), team) == []


def test_draft_advisory_is_never_listed(team, public_product):
    """Draft outranks visibility — an unpublished public advisory is still unpublished."""
    advisory = SecurityAdvisory.objects.create(team=team, title="Unfinished")
    AdvisoryProduct.objects.create(advisory=advisory, product=public_product)
    assert advisory.status == SecurityAdvisory.Status.DRAFT
    assert listed_ids(make_request(), team) == []


def test_public_advisory_is_listed_to_anonymous_visitors(team, public_product):
    advisory = advisory_for(team, public_product, visibility=SecurityAdvisory.Visibility.PUBLIC)
    assert listed_ids(make_request(), team) == [advisory.id]


def test_gated_advisory_is_hidden_from_anonymous_visitors(team, public_product):
    advisory_for(team, public_product, visibility=SecurityAdvisory.Visibility.GATED)
    payload = list_public_advisories(make_request(), team).value or {}
    assert payload["advisories"] == []
    # Counted, not merely dropped: the page tells the reader it exists.
    assert payload["hidden_count"] == 1


def test_gated_advisory_is_hidden_from_a_logged_in_stranger(team, public_product, guest_user):
    """Authentication alone is not the grant."""
    advisory_for(team, public_product, visibility=SecurityAdvisory.Visibility.GATED)
    assert listed_ids(make_request(guest_user), team) == []


def test_gated_advisory_is_visible_to_an_approved_customer(team, public_product, guest_user):
    advisory = advisory_for(team, public_product, visibility=SecurityAdvisory.Visibility.GATED)
    grant_gated_access(team, guest_user)
    assert listed_ids(make_request(guest_user), team) == [advisory.id]


def test_gated_advisory_is_visible_to_a_workspace_owner(team, public_product, sample_user):
    advisory = advisory_for(team, public_product, visibility=SecurityAdvisory.Visibility.GATED)
    assert listed_ids(make_request(sample_user), team) == [advisory.id]


# --- the per-product half of the gate ----------------------------------------


def test_gated_advisory_on_an_unlisted_product_is_hidden_from_a_customer(
    team, unlisted_product, guest_user
):
    """The grant is workspace-wide; the advisory is not.

    An approved customer holds access to what the trust center shows them. An
    advisory about a product that was never shown to anyone is not part of that,
    which is the whole reason the product check exists.
    """
    advisory_for(team, unlisted_product, visibility=SecurityAdvisory.Visibility.GATED)
    grant_gated_access(team, guest_user)
    assert listed_ids(make_request(guest_user), team) == []


def test_gated_advisory_on_an_unlisted_product_is_visible_to_an_owner(
    team, unlisted_product, sample_user
):
    """The people who wrote it can still read it; nobody else can."""
    advisory = advisory_for(team, unlisted_product, visibility=SecurityAdvisory.Visibility.GATED)
    assert listed_ids(make_request(sample_user), team) == [advisory.id]


def test_one_reachable_product_is_enough(team, public_product, unlisted_product, guest_user):
    """An advisory covering several products is readable via any one of them."""
    advisory = SecurityAdvisory.objects.create(team=team, title="Multi-product")
    AdvisoryProduct.objects.create(advisory=advisory, product=public_product)
    AdvisoryProduct.objects.create(advisory=advisory, product=unlisted_product)
    publish(advisory, visibility=SecurityAdvisory.Visibility.GATED)
    grant_gated_access(team, guest_user)

    assert listed_ids(make_request(guest_user), team) == [advisory.id]


def test_products_the_reader_cannot_see_are_not_named(
    team, public_product, unlisted_product, guest_user
):
    """Passing the gate on one product does not disclose the others' names."""
    advisory = SecurityAdvisory.objects.create(team=team, title="Multi-product")
    AdvisoryProduct.objects.create(advisory=advisory, product=public_product)
    AdvisoryProduct.objects.create(advisory=advisory, product=unlisted_product)
    publish(advisory, visibility=SecurityAdvisory.Visibility.GATED)
    grant_gated_access(team, guest_user)

    payload = list_public_advisories(make_request(guest_user), team).value or {}
    row = payload["advisories"][0]
    assert [p["name"] for p in row["products"]] == ["Acme Gateway"]
    assert row["withheld_product_count"] == 1


def test_a_gated_product_needs_the_grant_to_be_named(team, gated_product):
    """A public advisory can name a gated product only to readers who hold it."""
    advisory = SecurityAdvisory.objects.create(team=team, title="Vault issue")
    AdvisoryProduct.objects.create(advisory=advisory, product=gated_product)
    publish(advisory, visibility=SecurityAdvisory.Visibility.PUBLIC)

    row = (list_public_advisories(make_request(), team).value or {})["advisories"][0]
    assert row["products"] == []
    assert row["withheld_product_count"] == 1


def test_a_workspace_notice_needs_only_the_grant(team, guest_user):
    """A notice names no products, so there is nothing narrower to test."""
    advisory = SecurityAdvisory.objects.create(
        team=team,
        title="We investigated CVE-2021-44228",
        advisory_type=SecurityAdvisory.AdvisoryType.WORKSPACE_NOTICE,
    )
    publish(advisory, visibility=SecurityAdvisory.Visibility.GATED)

    assert listed_ids(make_request(guest_user), team) == []
    grant_gated_access(team, guest_user)
    assert listed_ids(make_request(guest_user), team) == [advisory.id]


# --- the detail page ---------------------------------------------------------


def test_detail_404s_rather_than_403s_for_a_gated_advisory(team, public_product, guest_user):
    """A 403 would confirm the advisory exists, which is what the embargo hides."""
    advisory = advisory_for(team, public_product, visibility=SecurityAdvisory.Visibility.GATED)
    result = get_public_advisory(make_request(guest_user), team, advisory.id)
    assert not result.ok
    assert result.status_code == 404


def test_detail_is_reachable_by_tracking_id(team, public_product):
    advisory = advisory_for(team, public_product, visibility=SecurityAdvisory.Visibility.PUBLIC)
    result = get_public_advisory(make_request(), team, advisory.tracking_id)
    assert result.ok
    assert result.value["pk"] == advisory.id


def test_another_workspaces_advisory_is_not_reachable(team, other_team, public_product):
    advisory = advisory_for(team, public_product, visibility=SecurityAdvisory.Visibility.PUBLIC)
    assert not get_public_advisory(make_request(), other_team, advisory.id).ok


def test_internal_comments_never_reach_the_timeline(team, public_product, sample_user):
    """COMMENT is workspace-only; UPDATE is the public-facing kind."""
    advisory = advisory_for(team, public_product, visibility=SecurityAdvisory.Visibility.PUBLIC)
    AdvisoryEvent.objects.create(
        advisory=advisory, event_type=AdvisoryEvent.EventType.COMMENT, body="Do not tell customers yet"
    )
    AdvisoryEvent.objects.create(
        advisory=advisory, event_type=AdvisoryEvent.EventType.UPDATE, body="Patch shipped in 1.4.3"
    )

    # Read as an owner, the widest reader there is — even they get the public feed.
    result = get_public_advisory(make_request(sample_user), team, advisory.id)
    notes = [entry["note"] for entry in result.value["timeline"]]
    assert "Patch shipped in 1.4.3" in notes
    assert "Do not tell customers yet" not in notes


def test_withdrawn_advisories_stay_readable(team, public_product):
    """Retracting a disclosure means saying so, not deleting the page."""
    advisory = advisory_for(team, public_product, visibility=SecurityAdvisory.Visibility.PUBLIC)
    advisory.status = SecurityAdvisory.Status.WITHDRAWN
    advisory.withdrawn_at = timezone.now()
    advisory.withdrawal_reason = "Reissued as ACME-SA-2026-0002."
    advisory.save()

    result = get_public_advisory(make_request(), team, advisory.id)
    assert result.ok
    assert result.value["is_withdrawn"]


# --- viewer scope and the landing-page summary -------------------------------


def test_a_guest_member_without_the_grant_has_no_gated_reach(team, public_product, guest_user):
    """Guest membership is not the same as an approved, NDA-signed grant."""
    Member.objects.create(team=team, user=guest_user, role="guest")
    scope = resolve_viewer_scope(make_request(guest_user), team)
    assert not scope.is_insider


def test_owner_scope_includes_unlisted_products(team, unlisted_product, sample_user):
    scope = resolve_viewer_scope(make_request(sample_user), team)
    assert scope.is_insider
    assert str(unlisted_product.id) in scope.product_ids


def test_anonymous_scope_excludes_gated_products(team, public_product, gated_product):
    scope = resolve_viewer_scope(make_request(), team)
    assert str(public_product.id) in scope.product_ids
    assert str(gated_product.id) not in scope.product_ids


def test_summary_counts_what_it_shows_and_what_it_withholds(team, public_product):
    advisory_for(team, public_product, visibility=SecurityAdvisory.Visibility.PUBLIC, title="Public one")
    advisory_for(team, public_product, visibility=SecurityAdvisory.Visibility.GATED, title="Gated one")

    summary = public_advisory_summary(make_request(), team)
    assert summary["total"] == 1
    assert summary["hidden_count"] == 1
    assert not summary["viewer_is_authenticated"]


def test_summary_limit_does_not_change_the_total(team, public_product):
    for index in range(5):
        advisory_for(
            team, public_product, visibility=SecurityAdvisory.Visibility.PUBLIC, title=f"Advisory {index}"
        )

    summary = public_advisory_summary(make_request(), team, limit=3)
    assert len(summary["recent"]) == 3
    assert summary["total"] == 5


# --- the index: version columns, filters, facets, sorting, pagination --------


def severities(team, public_product, values):
    for index, severity in enumerate(values):
        advisory = SecurityAdvisory.objects.create(
            team=team, title=f"Advisory {index}", severity=severity
        )
        AdvisoryProduct.objects.create(advisory=advisory, product=public_product)
        publish(advisory, visibility=SecurityAdvisory.Visibility.PUBLIC)


def browse(request, team, **params):
    """Run the index the way the view does, from query parameters."""
    query = parse_advisory_query(QueryDict(urlencode(params, doseq=True)))
    return browse_public_advisories(request, team, query).value or {}


def test_version_ranges_render_as_affected_and_unaffected(team, public_product):
    """The index answers "am I on an affected version", not "what is the interval"."""
    advisory = SecurityAdvisory.objects.create(team=team, title="Range test")
    advisory_product = AdvisoryProduct.objects.create(advisory=advisory, product=public_product)
    vulnerability = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-30001")
    status = AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        advisory_product=advisory_product,
        status=AdvisoryProductStatus.Status.EXPLOITABLE,
        action_statement="Upgrade.",
    )
    AdvisoryVersionRange.objects.create(product_status=status, introduced="2.0.0", fixed="2.4.1")
    publish(advisory, visibility=SecurityAdvisory.Visibility.PUBLIC)

    row = (list_public_advisories(make_request(), team).value or {})["advisories"][0]["affected_rows"][0]
    assert row["affected"] == ">= 2.0.0, < 2.4.1"
    assert row["unaffected"] == ">= 2.4.1"


def test_a_not_affected_product_reads_none_and_all(team, public_product):
    """No range can express "no version is affected", so the status short-circuits."""
    advisory = SecurityAdvisory.objects.create(team=team, title="Not affected")
    advisory_product = AdvisoryProduct.objects.create(advisory=advisory, product=public_product)
    vulnerability = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-30002")
    AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        advisory_product=advisory_product,
        status=AdvisoryProductStatus.Status.NOT_AFFECTED,
        justification=AdvisoryProductStatus.Justification.CODE_NOT_PRESENT,
    )
    publish(advisory, visibility=SecurityAdvisory.Visibility.PUBLIC)

    row = (list_public_advisories(make_request(), team).value or {})["advisories"][0]["affected_rows"][0]
    assert (row["affected"], row["unaffected"]) == ("None", "All")


def test_cvss_score_is_the_worst_across_vulnerabilities(team, public_product):
    """A three-CVE advisory must not read as its mildest CVE."""
    advisory = SecurityAdvisory.objects.create(team=team, title="Multi-CVE")
    AdvisoryProduct.objects.create(advisory=advisory, product=public_product)
    for cve, score in (("CVE-2026-30003", 4.2), ("CVE-2026-30004", 9.8)):
        AdvisoryVulnerability.objects.create(
            advisory=advisory, cve_id=cve, cvss_scores=[{"version": "3.1", "base_score": score}]
        )
    publish(advisory, visibility=SecurityAdvisory.Visibility.PUBLIC)

    assert (list_public_advisories(make_request(), team).value or {})["advisories"][0]["cvss_score"] == 9.8


def test_a_malformed_cvss_entry_does_not_break_the_page(team, public_product):
    advisory = SecurityAdvisory.objects.create(team=team, title="Bad score")
    AdvisoryProduct.objects.create(advisory=advisory, product=public_product)
    AdvisoryVulnerability.objects.create(
        advisory=advisory, cve_id="CVE-2026-30005", cvss_scores=[{"version": "3.1"}, "nonsense"]
    )
    publish(advisory, visibility=SecurityAdvisory.Visibility.PUBLIC)

    assert (list_public_advisories(make_request(), team).value or {})["advisories"][0]["cvss_score"] is None


def test_severity_filter_narrows_the_list(team, public_product):
    severities(team, public_product, ["critical", "high", "low"])
    payload = browse(make_request(), team, severity=["critical", "high"])
    assert payload["total"] == 2
    assert {a["severity"] for a in payload["advisories"]} == {"critical", "high"}


def test_severity_facet_counts_ignore_the_severity_filter(team, public_product):
    """Ticking one severity must not zero the others, or the filter is a dead end."""
    severities(team, public_product, ["critical", "high", "high"])
    payload = browse(make_request(), team, severity=["critical"])
    counts = {f["value"]: f["count"] for f in payload["facets"]["severity"]}
    assert counts["critical"] == 1
    assert counts["high"] == 2


def test_product_facet_counts_only_visible_products(team, public_product, gated_product):
    """A facet must never name a product the reader cannot be shown."""
    advisory = SecurityAdvisory.objects.create(team=team, title="Vault only")
    AdvisoryProduct.objects.create(advisory=advisory, product=gated_product)
    publish(advisory, visibility=SecurityAdvisory.Visibility.PUBLIC)

    payload = browse(make_request(), team)
    assert [f["label"] for f in payload["facets"]["product"]] == []


def test_unknown_severity_values_are_dropped(team, public_product):
    """A hand-edited query string cannot smuggle a filter value past the facets."""
    severities(team, public_product, ["critical"])
    query = parse_advisory_query(QueryDict("severity=critical&severity=bogus"))
    assert query.severities == frozenset({"critical"})


def test_sorting_by_severity_puts_the_worst_first(team, public_product):
    severities(team, public_product, ["low", "critical", "medium"])
    payload = browse(make_request(), team, sort="severity")
    assert [a["severity"] for a in payload["advisories"]] == ["critical", "medium", "low"]


def test_pagination_reports_a_stable_window(team, public_product):
    severities(team, public_product, ["low"] * 30)
    first = browse(make_request(), team)
    assert (first["start_index"], first["end_index"], first["total"]) == (1, 25, 30)
    assert first["has_next"] and not first["has_prev"]

    second = browse(make_request(), team, page=2)
    assert (second["start_index"], second["end_index"]) == (26, 30)
    assert second["has_prev"] and not second["has_next"]


def test_an_out_of_range_page_clamps_to_the_last_one(team, public_product):
    """A stale bookmark should land on the last page, not on an empty one."""
    severities(team, public_product, ["low"] * 3)
    payload = browse(make_request(), team, page=99)
    assert payload["page"] == 1
    assert len(payload["advisories"]) == 3


def test_a_published_date_range_filters_the_list(team, public_product):
    severities(team, public_product, ["low"])
    today = timezone.now().date().isoformat()
    assert browse(make_request(), team, **{"from": today})["total"] == 1
    assert browse(make_request(), team, to="2000-01-01")["total"] == 0


def test_an_unparseable_date_drops_the_filter_rather_than_raising(team, public_product):
    severities(team, public_product, ["low"])
    assert browse(make_request(), team, **{"from": "not-a-date"})["total"] == 1

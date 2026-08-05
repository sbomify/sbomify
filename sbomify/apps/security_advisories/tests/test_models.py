"""Security advisory data model: one test per field-dependency rule."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from sbomify.apps.core.models import Component, Product, Release
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.security_advisories.models import (
    CVE_ID_RE,
    AdvisoryEvent,
    AdvisoryProduct,
    AdvisoryProductStatus,
    AdvisoryReference,
    AdvisoryVersionRange,
    AdvisoryVulnerability,
    ReferenceType,
    SecurityAdvisory,
    detect_reference_type,
    validate_publishable,
)

from .conftest import publish

pytestmark = pytest.mark.django_db


# --- vocabulary: the stored values must not drift from the triage canon --------


def test_status_values_are_triage_states() -> None:
    """Advisory statuses are CycloneDX states the rest of the codebase uses.

    A subset, not the whole vocabulary. An advisory status is what a published
    advisory tells a reader about a product; risk_accepted is an internal
    decision carrying an owner and an expiry, and "we accepted the risk" is not
    a statement a workspace publishes about its own product.
    """
    from sbomify.apps.vulnerability_scanning.triage import TRIAGE_STATES

    assert {choice.value for choice in AdvisoryProductStatus.Status} <= set(TRIAGE_STATES)


def test_risk_accepted_is_not_an_advisory_status() -> None:
    """Pinned so adding it becomes a decision rather than a slip."""
    assert "risk_accepted" not in {choice.value for choice in AdvisoryProductStatus.Status}


def test_justification_values_match_triage_justifications() -> None:
    from sbomify.apps.vulnerability_scanning.triage import TRIAGE_JUSTIFICATIONS

    assert {choice.value for choice in AdvisoryProductStatus.Justification} == set(TRIAGE_JUSTIFICATIONS)


def test_suppressing_states_match_vex() -> None:
    """The states that clear a finding agree with the VEX applier."""
    from sbomify.apps.vulnerability_scanning.vex import _SUPPRESSING_STATES

    assert {value for value in AdvisoryProductStatus.SUPPRESSING_STATES} == set(_SUPPRESSING_STATES)


def test_false_positive_is_storable() -> None:
    """The state OpenVEX and CSAF cannot express still round-trips here."""
    assert AdvisoryProductStatus.Status.FALSE_POSITIVE.value == "false_positive"


# --- D1/D2: published requires published_at and tracking_id -------------------


def test_published_requires_published_at_and_tracking_id(advisory) -> None:
    advisory.status = SecurityAdvisory.Status.PUBLISHED
    with pytest.raises(ValidationError) as exc:
        advisory.save()
    assert set(exc.value.message_dict) == {"published_at", "tracking_id"}


def test_published_at_without_publish_status_rejected(advisory) -> None:
    advisory.published_at = timezone.now()
    with pytest.raises(ValidationError, match="cannot be a draft"):
        advisory.save()


# --- D3/D4: withdrawal ---------------------------------------------------------


def test_withdrawn_requires_timestamp_and_reason(make_publishable) -> None:
    advisory = publish(make_publishable)
    advisory.status = SecurityAdvisory.Status.WITHDRAWN
    with pytest.raises(ValidationError) as exc:
        advisory.save()
    assert set(exc.value.message_dict) == {"withdrawn_at", "withdrawal_reason"}


def test_draft_cannot_be_withdrawn(advisory) -> None:
    advisory.status = SecurityAdvisory.Status.WITHDRAWN
    advisory.withdrawn_at = timezone.now()
    advisory.withdrawal_reason = "Filed by mistake."
    with pytest.raises(ValidationError, match="delete drafts instead"):
        advisory.save()


def test_withdrawal_fields_without_withdrawn_status_rejected(make_publishable) -> None:
    advisory = publish(make_publishable)
    advisory.withdrawal_reason = "Superseded."
    with pytest.raises(ValidationError, match="status must be withdrawn"):
        advisory.save()


# --- D5: tracking_id and team immutable after publish -------------------------


def test_tracking_id_is_immutable_once_assigned(make_publishable) -> None:
    advisory = publish(make_publishable)
    advisory.tracking_id = "SOMETHING-ELSE-0001"
    with pytest.raises(ValidationError, match="immutable"):
        advisory.save()


def test_advisory_cannot_change_workspace(make_publishable, other_team) -> None:
    advisory = publish(make_publishable)
    advisory.team = other_team
    with pytest.raises(ValidationError, match="cannot move between workspaces"):
        advisory.save()


# --- D17: made_public_at is write-once ----------------------------------------


def test_going_public_records_when(make_publishable) -> None:
    advisory = publish(make_publishable)
    advisory.visibility = SecurityAdvisory.Visibility.PUBLIC
    with pytest.raises(ValidationError, match="must record when"):
        advisory.save()


def test_made_public_at_cannot_be_cleared(make_publishable) -> None:
    advisory = publish(make_publishable, visibility=SecurityAdvisory.Visibility.PUBLIC)
    advisory.visibility = SecurityAdvisory.Visibility.GATED
    advisory.made_public_at = None
    with pytest.raises(ValidationError, match="cannot be changed"):
        advisory.save()


def test_made_public_at_cannot_be_rewritten(make_publishable) -> None:
    """Write-once, not merely non-null: moving the timestamp would rewrite when
    disclosure happened."""
    advisory = publish(make_publishable, visibility=SecurityAdvisory.Visibility.PUBLIC)
    advisory.made_public_at = advisory.made_public_at - timedelta(days=30)
    with pytest.raises(ValidationError, match="cannot be changed"):
        advisory.save()


def test_re_embargoing_keeps_the_disclosure_record(make_publishable) -> None:
    advisory = publish(make_publishable, visibility=SecurityAdvisory.Visibility.PUBLIC)
    disclosed_at = advisory.made_public_at
    advisory.visibility = SecurityAdvisory.Visibility.GATED
    advisory.save()
    advisory.refresh_from_db()
    assert advisory.made_public_at == disclosed_at


# --- D18: a draft is never externally visible ---------------------------------


def test_draft_is_never_externally_visible(advisory) -> None:
    advisory.visibility = SecurityAdvisory.Visibility.PUBLIC
    advisory.save()
    assert advisory.is_externally_visible is False


def test_draft_cannot_carry_a_disclosure_timestamp(advisory) -> None:
    """Otherwise a draft could be backdated, then publishing would freeze that
    date under the write-once rule."""
    advisory.made_public_at = timezone.now() - timedelta(days=90)
    with pytest.raises(ValidationError, match="A draft has not been disclosed"):
        advisory.save()


def test_published_public_advisory_is_externally_visible(make_publishable) -> None:
    advisory = publish(make_publishable, visibility=SecurityAdvisory.Visibility.PUBLIC)
    assert advisory.is_externally_visible is True


# --- tracking_id allocation ----------------------------------------------------


def test_tracking_ids_increment_per_team_and_year(team, advisory) -> None:
    first = SecurityAdvisory.allocate_tracking_id(team, prefix="ACME", year=2026)
    assert first == "ACME-SA-2026-0001"

    advisory.tracking_id = first
    advisory.published_at = timezone.now()
    advisory.status = SecurityAdvisory.Status.PUBLISHED
    advisory.save()

    assert SecurityAdvisory.allocate_tracking_id(team, prefix="ACME", year=2026) == "ACME-SA-2026-0002"
    # The sequence restarts each year, matching CVE and CSAF practice.
    assert SecurityAdvisory.allocate_tracking_id(team, prefix="ACME", year=2027) == "ACME-SA-2027-0001"


def test_tracking_id_unique_per_team(team, advisory) -> None:
    advisory.tracking_id = "ACME-SA-2026-0001"
    advisory.published_at = timezone.now()
    advisory.status = SecurityAdvisory.Status.PUBLISHED
    advisory.save()

    other = SecurityAdvisory(team=team, title="Second", tracking_id="ACME-SA-2026-0001")
    other.published_at = timezone.now()
    other.status = SecurityAdvisory.Status.PUBLISHED
    with pytest.raises(IntegrityError), transaction.atomic():
        other.save()


def test_draft_cannot_hold_a_tracking_id(team) -> None:
    """Publishing assigns the id. A draft holding one would also burn a number
    out of that year's sequence."""
    advisory = SecurityAdvisory(team=team, title="Draft", tracking_id="ACME-SA-2026-0001")
    with pytest.raises(ValidationError, match="A draft has no tracking id"):
        advisory.save()


def test_withdrawn_advisory_keeps_its_tracking_id(team) -> None:
    """The id outlives the withdrawal, so a consumer can still resolve it."""
    advisory = SecurityAdvisory(
        team=team,
        title="Withdrawn",
        status=SecurityAdvisory.Status.WITHDRAWN,
        published_at=timezone.now(),
        withdrawn_at=timezone.now(),
        withdrawal_reason="Superseded.",
    )
    with pytest.raises(ValidationError, match="must have a tracking id"):
        advisory.save()


def test_whitespace_tracking_id_does_not_count_as_published(team) -> None:
    """Whitespace would otherwise satisfy the published check and sit outside the
    partial unique's blank-draft exemption, so two of them could collide."""
    advisory = SecurityAdvisory(
        team=team,
        title="Published",
        status=SecurityAdvisory.Status.PUBLISHED,
        published_at=timezone.now(),
        tracking_id="   ",
    )
    with pytest.raises(ValidationError, match="must have a tracking id"):
        advisory.save()


def test_blank_tracking_ids_do_not_collide(team) -> None:
    """The unique constraint is partial, so any number of drafts coexist."""
    SecurityAdvisory.objects.create(team=team, title="Draft one")
    SecurityAdvisory.objects.create(team=team, title="Draft two")
    assert SecurityAdvisory.objects.filter(team=team, tracking_id="").count() == 2


# --- D9: a vulnerability needs a CVE id or a title ----------------------------


def test_vulnerability_needs_cve_or_title(advisory) -> None:
    with pytest.raises(ValidationError, match="CVE id or a title"):
        AdvisoryVulnerability.objects.create(advisory=advisory)


def test_vulnerability_accepts_title_without_cve(advisory) -> None:
    vuln = AdvisoryVulnerability.objects.create(advisory=advisory, title="Unassigned auth bypass")
    assert vuln.cve_id == ""


@pytest.mark.parametrize("bad", ["CVE-21-4", "CVE-2021-123", "GHSA-xxxx", "cve-2021-44228"])
def test_malformed_cve_id_rejected(advisory, bad) -> None:
    with pytest.raises(ValidationError, match="not a CVE id"):
        AdvisoryVulnerability.objects.create(advisory=advisory, cve_id=bad)


def test_cve_id_sequence_may_exceed_four_digits(advisory) -> None:
    vuln = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-1234567")
    assert vuln.cve_id == "CVE-2026-1234567"


def test_column_accepts_every_id_the_validator_accepts(advisory) -> None:
    """The sequence part has no upper bound, so the column must not impose one
    the validator does not."""
    long_id = "CVE-2026-" + "1" * 20
    assert CVE_ID_RE.match(long_id)
    vuln = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id=long_id)
    vuln.refresh_from_db()
    assert vuln.cve_id == long_id


def test_cve_unique_per_advisory(advisory, vulnerability) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        AdvisoryVulnerability.objects.create(advisory=advisory, cve_id=vulnerability.cve_id)


# --- external reference enum ---------------------------------------------------


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("CVE-2021-44228", ReferenceType.CVE),
        ("GHSA-jfh8-c2jp-5v3q", ReferenceType.GHSA),
        ("ghsa-jfh8-c2jp-5v3q", ReferenceType.GHSA),
        ("EUVD-2024-0001", ReferenceType.EUVD),
        ("PYSEC-2021-19", ReferenceType.PYSEC),
        ("RUSTSEC-2021-0093", ReferenceType.RUSTSEC),
        ("GO-2021-0113", ReferenceType.GO),
        ("USN-5192-1", ReferenceType.USN),
        ("RHSA-2021:5106", ReferenceType.RHSA),
        ("VU#930724", ReferenceType.CERT_VU),
        ("MAL-2024-1", ReferenceType.MAL),
        ("something-else", ReferenceType.OTHER),
        ("", ReferenceType.OTHER),
        (None, ReferenceType.OTHER),
    ],
)
def test_detect_reference_type(identifier, expected) -> None:
    assert detect_reference_type(identifier) == expected


def test_reference_type_classified_on_save(advisory, vulnerability) -> None:
    reference = AdvisoryReference.objects.create(
        advisory=advisory, vulnerability=vulnerability, external_id="GHSA-jfh8-c2jp-5v3q"
    )
    assert reference.reference_type == ReferenceType.GHSA


def test_explicit_reference_type_is_not_overwritten(advisory) -> None:
    """An id no prefix recognises is the only case where the caller's type adds
    something the id does not already say."""
    reference = AdvisoryReference.objects.create(
        advisory=advisory, external_id="ACME-2026-1", reference_type=ReferenceType.MSRC
    )
    assert reference.reference_type == ReferenceType.MSRC


def test_editing_the_id_reclassifies_the_reference(advisory) -> None:
    reference = AdvisoryReference.objects.create(advisory=advisory, external_id="CVE-2021-44228")
    reference.external_id = "GHSA-jfh8-c2jp-5v3q"
    reference.save()
    reference.refresh_from_db()
    assert reference.reference_type == ReferenceType.GHSA


def test_a_recognised_prefix_beats_a_contradicting_type(advisory) -> None:
    reference = AdvisoryReference.objects.create(
        advisory=advisory, external_id="CVE-2021-44228", reference_type=ReferenceType.GHSA
    )
    assert reference.reference_type == ReferenceType.CVE


def test_reference_needs_id_or_url(advisory) -> None:
    with pytest.raises(ValidationError, match="identifier or a URL"):
        AdvisoryReference.objects.create(advisory=advisory)


def test_invalid_reference_url_rejected(advisory) -> None:
    """save() runs the field validators, so URLField's own check applies outside
    a ModelForm too."""
    with pytest.raises(ValidationError, match="[Ee]nter a valid URL"):
        AdvisoryReference.objects.create(advisory=advisory, url="not a url at all")


def test_invalid_choice_rejected(vulnerability, advisory_product) -> None:
    with pytest.raises(ValidationError, match="not a valid choice"):
        AdvisoryProductStatus.objects.create(
            vulnerability=vulnerability, advisory_product=advisory_product, status="bogus"
        )


def test_whitespace_only_reference_rejected(advisory) -> None:
    """Whitespace would otherwise satisfy both the emptiness check and the
    CheckConstraint."""
    with pytest.raises(ValidationError, match="identifier or a URL"):
        AdvisoryReference.objects.create(advisory=advisory, external_id="   ", url="  ")


def test_reference_id_is_stripped_before_classification(advisory) -> None:
    reference = AdvisoryReference.objects.create(advisory=advisory, external_id="  CVE-2021-44228  ")
    assert reference.external_id == "CVE-2021-44228"
    assert reference.reference_type == ReferenceType.CVE


def test_reference_url_only_is_allowed(advisory) -> None:
    reference = AdvisoryReference.objects.create(advisory=advisory, url="https://example.test/psirt/1")
    assert reference.reference_type == ReferenceType.OTHER


def test_reference_vulnerability_must_share_the_advisory(advisory, vulnerability, team) -> None:
    other = SecurityAdvisory.objects.create(team=team, title="Other")
    with pytest.raises(ValidationError, match="different advisory"):
        AdvisoryReference.objects.create(advisory=other, vulnerability=vulnerability, external_id="CVE-2021-44228")


# --- D6/D7: advisory type governs product rows --------------------------------


def test_workspace_notice_names_no_products(notice, product) -> None:
    with pytest.raises(ValidationError, match="names no products"):
        AdvisoryProduct.objects.create(advisory=notice, product=product)


def test_product_name_snapshots_on_save(advisory, product) -> None:
    link = AdvisoryProduct.objects.create(advisory=advisory, product=product)
    assert link.product_name == "Acme Gateway"


def test_product_name_survives_product_deletion(advisory, product) -> None:
    link = AdvisoryProduct.objects.create(advisory=advisory, product=product)
    product.delete()
    link.refresh_from_db()
    assert link.product_id is None
    assert link.product_name == "Acme Gateway"


def test_product_row_needs_a_product_or_a_name(advisory) -> None:
    """Neither leaves a row naming nothing a reader can identify."""
    with pytest.raises(ValidationError, match="needs a product or a name"):
        AdvisoryProduct.objects.create(advisory=advisory)


def test_whitespace_product_name_falls_back_to_the_snapshot(advisory, product) -> None:
    """A blank-looking name must not beat the snapshot and leave an unreadable row."""
    link = AdvisoryProduct.objects.create(advisory=advisory, product=product, product_name="   ")
    assert link.product_name == "Acme Gateway"


def test_whitespace_product_name_without_a_product_rejected(advisory) -> None:
    with pytest.raises(ValidationError, match="needs a product or a name"):
        AdvisoryProduct.objects.create(advisory=advisory, product_name="   ")


def test_product_row_may_carry_a_name_alone(advisory) -> None:
    """A product retired before sbomify tracked it is still nameable."""
    link = AdvisoryProduct.objects.create(advisory=advisory, product_name="Legacy Appliance")
    assert link.product_id is None


def test_advisory_cannot_become_a_notice_while_it_names_products(advisory, advisory_product) -> None:
    advisory.advisory_type = SecurityAdvisory.AdvisoryType.WORKSPACE_NOTICE
    with pytest.raises(ValidationError, match="cannot become a workspace notice"):
        advisory.save()


def test_advisory_becomes_a_notice_once_its_products_are_gone(advisory, advisory_product) -> None:
    advisory_product.delete()
    advisory.advisory_type = SecurityAdvisory.AdvisoryType.WORKSPACE_NOTICE
    advisory.save()
    advisory.refresh_from_db()
    assert advisory.advisory_type == SecurityAdvisory.AdvisoryType.WORKSPACE_NOTICE


def test_cross_tenant_product_rejected(advisory, other_team) -> None:
    foreign = Product.objects.create(name="Someone else's", team=other_team)
    with pytest.raises(ValidationError, match="Cross-tenant"):
        AdvisoryProduct.objects.create(advisory=advisory, product=foreign)


def test_product_unique_per_advisory(advisory, product, advisory_product) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        AdvisoryProduct.objects.create(advisory=advisory, product=product)


# --- D13/D15/D19: product status rules ----------------------------------------


def test_justification_requires_not_affected(vulnerability, advisory_product) -> None:
    with pytest.raises(ValidationError, match="only applies to a not_affected"):
        AdvisoryProductStatus.objects.create(
            vulnerability=vulnerability,
            advisory_product=advisory_product,
            status=AdvisoryProductStatus.Status.EXPLOITABLE,
            justification=AdvisoryProductStatus.Justification.CODE_NOT_PRESENT,
        )


def test_status_spanning_two_advisories_rejected(vulnerability, team, product) -> None:
    other = SecurityAdvisory.objects.create(team=team, title="Other")
    other_product = AdvisoryProduct.objects.create(advisory=other, product=product)
    with pytest.raises(ValidationError, match="different advisories"):
        AdvisoryProductStatus.objects.create(vulnerability=vulnerability, advisory_product=other_product)


def test_one_status_per_vulnerability_and_product(vulnerability, advisory_product) -> None:
    AdvisoryProductStatus.objects.create(vulnerability=vulnerability, advisory_product=advisory_product)
    with pytest.raises(IntegrityError), transaction.atomic():
        AdvisoryProductStatus.objects.create(vulnerability=vulnerability, advisory_product=advisory_product)


def test_one_portfolio_status_per_vulnerability(vulnerability) -> None:
    AdvisoryProductStatus.objects.create(vulnerability=vulnerability)
    with pytest.raises(IntegrityError), transaction.atomic():
        AdvisoryProductStatus.objects.create(vulnerability=vulnerability)


def test_source_vex_must_be_a_vex_artifact(vulnerability, team) -> None:
    component = Component.objects.create(name="gateway", team=team)
    sbom = SBOM.objects.create(name="gateway", component=component, format="cyclonedx", bom_type=SBOM.BomType.SBOM)
    with pytest.raises(ValidationError, match="must point at a VEX artifact"):
        AdvisoryProductStatus.objects.create(vulnerability=vulnerability, source_vex=sbom)


def test_source_vex_must_belong_to_the_same_workspace(vulnerability, other_team) -> None:
    component = Component.objects.create(name="foreign", team=other_team)
    vex = SBOM.objects.create(name="foreign", component=component, format="cyclonedx", bom_type=SBOM.BomType.VEX)
    with pytest.raises(ValidationError, match="different workspace"):
        AdvisoryProductStatus.objects.create(vulnerability=vulnerability, source_vex=vex)


def test_manual_status_cannot_cite_a_source_vex(vulnerability, team) -> None:
    component = Component.objects.create(name="gateway", team=team)
    vex = SBOM.objects.create(name="gateway-vex", component=component, format="cyclonedx", bom_type=SBOM.BomType.VEX)
    with pytest.raises(ValidationError, match="manual status cannot cite"):
        AdvisoryProductStatus.objects.create(
            vulnerability=vulnerability, source=AdvisoryProductStatus.Source.MANUAL, source_vex=vex
        )


def test_recommended_release_must_belong_to_the_product(vulnerability, advisory_product, team) -> None:
    other_product = Product.objects.create(name="Acme Relay", team=team)
    release = Release.objects.create(product=other_product, name="9.9.9", version="9.9.9")
    with pytest.raises(ValidationError, match="recommended release belongs to a different product"):
        AdvisoryProductStatus.objects.create(
            vulnerability=vulnerability, advisory_product=advisory_product, recommended_release=release
        )


def test_portfolio_status_cannot_recommend_a_release(vulnerability, product) -> None:
    release = Release.objects.create(product=product, name="1.4.3", version="1.4.3")
    with pytest.raises(ValidationError, match="cannot recommend a release"):
        AdvisoryProductStatus.objects.create(vulnerability=vulnerability, recommended_release=release)


def test_name_only_product_cannot_recommend_a_release(advisory, vulnerability, product) -> None:
    """Same reasoning as the version-range pin: no Product, no releases of its own."""
    external = AdvisoryProduct.objects.create(advisory=advisory, product_name="Acme Gateway (OEM build)")
    release = Release.objects.create(product=product, name="1.4.3", version="1.4.3")
    with pytest.raises(ValidationError, match="no sbomify record"):
        AdvisoryProductStatus.objects.create(
            vulnerability=vulnerability, advisory_product=external, recommended_release=release
        )


def test_recommended_release_on_its_own_product_is_accepted(vulnerability, advisory_product, product) -> None:
    release = Release.objects.create(product=product, name="1.4.3", version="1.4.3")
    status = AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        advisory_product=advisory_product,
        status=AdvisoryProductStatus.Status.RESOLVED,
        recommended_release=release,
    )
    assert status.recommended_release_id == release.id


def test_vex_import_records_its_source(vulnerability, team) -> None:
    component = Component.objects.create(name="gateway", team=team)
    vex = SBOM.objects.create(name="gateway-vex", component=component, format="cyclonedx", bom_type=SBOM.BomType.VEX)
    status = AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        status=AdvisoryProductStatus.Status.NOT_AFFECTED,
        justification=AdvisoryProductStatus.Justification.REQUIRES_CONFIGURATION,
        source=AdvisoryProductStatus.Source.VEX_IMPORT,
        source_vex=vex,
    )
    # A justification with no CISA equivalent survives the round trip.
    assert status.justification == "requires_configuration"
    assert status.is_suppressing is True


# --- D14: version ranges -------------------------------------------------------


@pytest.fixture
def status(vulnerability, advisory_product):
    return AdvisoryProductStatus.objects.create(vulnerability=vulnerability, advisory_product=advisory_product)


def test_range_needs_an_endpoint(status) -> None:
    with pytest.raises(ValidationError, match="at least one endpoint"):
        AdvisoryVersionRange.objects.create(product_status=status)


def test_range_rejects_fixed_and_last_affected_together(status) -> None:
    with pytest.raises(ValidationError, match="not both"):
        AdvisoryVersionRange.objects.create(product_status=status, fixed="1.4.3", last_affected="1.4.2")


def test_open_ended_range_is_allowed(status) -> None:
    """An advisory has to say "everything from 1.2.0 on" before a fix exists."""
    version_range = AdvisoryVersionRange.objects.create(product_status=status, introduced="1.2.0")
    assert str(version_range) == "[1.2.0, *)"


def test_range_from_the_beginning(status) -> None:
    version_range = AdvisoryVersionRange.objects.create(product_status=status, fixed="1.4.3")
    assert str(version_range) == "[*, 1.4.3)"


def test_release_pin_fills_the_version_string(status, product) -> None:
    release = Release.objects.create(product=product, name="1.4.3", version="1.4.3")
    version_range = AdvisoryVersionRange.objects.create(
        product_status=status, introduced="1.2.0", fixed_release=release
    )
    assert version_range.fixed == "1.4.3"


def test_explicit_string_wins_over_the_pin(status, product) -> None:
    release = Release.objects.create(product=product, name="1.4.3", version="1.4.3")
    version_range = AdvisoryVersionRange.objects.create(
        product_status=status, fixed="1.4.3-hotfix", fixed_release=release
    )
    assert version_range.fixed == "1.4.3-hotfix"


def test_version_string_survives_release_deletion(status, product) -> None:
    release = Release.objects.create(product=product, name="1.4.3", version="1.4.3")
    version_range = AdvisoryVersionRange.objects.create(product_status=status, fixed_release=release)
    release.delete()
    version_range.refresh_from_db()
    assert version_range.fixed_release_id is None
    assert version_range.fixed == "1.4.3"


def test_pin_from_another_product_rejected(status, team) -> None:
    other_product = Product.objects.create(name="Other product", team=team)
    release = Release.objects.create(product=other_product, name="9.9.9", version="9.9.9")
    with pytest.raises(ValidationError, match="different product"):
        AdvisoryVersionRange.objects.create(product_status=status, fixed_release=release)


def test_name_only_product_cannot_pin_releases(advisory, vulnerability, product) -> None:
    """A row naming a product sbomify does not host has no releases of its own.

    ``Release.product`` cascades, so a live pin under a NULL ``product`` is never
    a leftover from a deleted product: it always points somewhere else.
    """
    external = AdvisoryProduct.objects.create(advisory=advisory, product_name="Acme Gateway (OEM build)")
    name_only_status = AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        advisory_product=external,
        status=AdvisoryProductStatus.Status.EXPLOITABLE,
        action_statement="Contact the vendor.",
    )
    release = Release.objects.create(product=product, name="1.0.0", version="1.0.0")
    with pytest.raises(ValidationError) as exc:
        AdvisoryVersionRange.objects.create(product_status=name_only_status, fixed_release=release)
    assert set(exc.value.message_dict) == {"fixed_release"}


def test_portfolio_status_cannot_pin_releases(vulnerability, product) -> None:
    portfolio = AdvisoryProductStatus.objects.create(vulnerability=vulnerability)
    release = Release.objects.create(product=product, name="1.0.0", version="1.0.0")
    with pytest.raises(ValidationError, match="cannot pin releases"):
        AdvisoryVersionRange.objects.create(product_status=portfolio, fixed_release=release)


def test_portfolio_pin_error_names_the_field_that_was_set(vulnerability, product) -> None:
    """A form has to highlight the pin the caller set, not always the first one."""
    portfolio = AdvisoryProductStatus.objects.create(vulnerability=vulnerability)
    release = Release.objects.create(product=product, name="1.0.0", version="1.0.0")
    with pytest.raises(ValidationError) as exc:
        AdvisoryVersionRange.objects.create(product_status=portfolio, last_affected_release=release)
    assert set(exc.value.message_dict) == {"last_affected_release"}


# --- D16 + append-only: the timeline ------------------------------------------


def test_comment_needs_a_body(advisory) -> None:
    with pytest.raises(ValidationError, match="Comment events need a body"):
        AdvisoryEvent.objects.create(advisory=advisory, event_type=AdvisoryEvent.EventType.COMMENT)


def test_update_needs_a_body_and_reads_as_english(advisory) -> None:
    """The message carries the label, so no event type produces "A update event"."""
    with pytest.raises(ValidationError, match="Update events need a body"):
        AdvisoryEvent.objects.create(advisory=advisory, event_type=AdvisoryEvent.EventType.UPDATE)


def test_field_change_needs_a_typed_payload(advisory) -> None:
    with pytest.raises(ValidationError, match="payload needs"):
        AdvisoryEvent.objects.create(
            advisory=advisory, event_type=AdvisoryEvent.EventType.FIELD_CHANGE, payload={"field": "severity"}
        )


def test_field_change_with_full_payload_is_accepted(advisory) -> None:
    event = AdvisoryEvent.objects.create(
        advisory=advisory,
        event_type=AdvisoryEvent.EventType.FIELD_CHANGE,
        payload={"field": "severity", "old": "medium", "new": "critical"},
    )
    assert event.payload["new"] == "critical"


def test_events_cannot_be_edited(advisory) -> None:
    event = AdvisoryEvent.objects.create(
        advisory=advisory, event_type=AdvisoryEvent.EventType.UPDATE, body="Investigating."
    )
    event.body = "Rewritten."
    with pytest.raises(ValidationError, match="append-only"):
        event.save()


def test_events_cannot_be_deleted(advisory) -> None:
    event = AdvisoryEvent.objects.create(
        advisory=advisory, event_type=AdvisoryEvent.EventType.UPDATE, body="Investigating."
    )
    with pytest.raises(ValidationError, match="append-only"):
        event.delete()


def test_events_cannot_be_bulk_updated(advisory) -> None:
    """QuerySet.update() never calls save(), so the manager has to refuse it."""
    AdvisoryEvent.objects.create(advisory=advisory, event_type=AdvisoryEvent.EventType.UPDATE, body="Investigating.")
    with pytest.raises(ValidationError, match="append-only"):
        AdvisoryEvent.objects.filter(advisory=advisory).update(body="Rewritten.")


def test_events_cannot_be_bulk_deleted(advisory) -> None:
    AdvisoryEvent.objects.create(advisory=advisory, event_type=AdvisoryEvent.EventType.UPDATE, body="Investigating.")
    with pytest.raises(ValidationError, match="append-only"):
        AdvisoryEvent.objects.filter(advisory=advisory).delete()


def test_comments_are_not_public(advisory) -> None:
    assert AdvisoryEvent.EventType.COMMENT not in AdvisoryEvent.PUBLIC_EVENT_TYPES
    assert AdvisoryEvent.EventType.UPDATE in AdvisoryEvent.PUBLIC_EVENT_TYPES


def test_cra_reporting_leaves_a_trail(advisory, sample_user) -> None:
    """Article 14 runs 24h early warning, 72h notification, then a final report."""
    for event_type in (
        AdvisoryEvent.EventType.CRA_EARLY_WARNING,
        AdvisoryEvent.EventType.CRA_NOTIFICATION,
        AdvisoryEvent.EventType.CRA_FINAL_REPORT,
        AdvisoryEvent.EventType.USERS_NOTIFIED,
    ):
        AdvisoryEvent.objects.create(advisory=advisory, event_type=event_type, actor=sample_user)
    assert advisory.events.count() == 4


def test_timeline_is_chronological(advisory) -> None:
    AdvisoryEvent.objects.create(advisory=advisory, event_type=AdvisoryEvent.EventType.UPDATE, body="First.")
    AdvisoryEvent.objects.create(advisory=advisory, event_type=AdvisoryEvent.EventType.UPDATE, body="Second.")
    assert [event.body for event in advisory.events.all()] == ["First.", "Second."]


# --- exploitation status (CRA trigger) ----------------------------------------


def test_exploitation_status_defaults_to_unknown(vulnerability) -> None:
    assert vulnerability.exploitation_status == AdvisoryVulnerability.ExploitationStatus.UNKNOWN


def test_actively_exploited_is_queryable(advisory) -> None:
    AdvisoryVulnerability.objects.create(
        advisory=advisory,
        cve_id="CVE-2021-44228",
        exploitation_status=AdvisoryVulnerability.ExploitationStatus.KNOWN_EXPLOITED,
    )
    AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2021-45046")
    exploited = AdvisoryVulnerability.objects.filter(
        exploitation_status=AdvisoryVulnerability.ExploitationStatus.KNOWN_EXPLOITED
    )
    assert exploited.count() == 1


# --- D7/D8/D10/D11/D12: publish validation ------------------------------------


def test_publishable_advisory_has_no_complaints(make_publishable) -> None:
    assert validate_publishable(make_publishable) == []


def test_product_advisory_needs_a_product(advisory) -> None:
    assert "A product advisory needs at least one product." in validate_publishable(advisory)


def test_workspace_notice_needs_a_portfolio_status(notice) -> None:
    AdvisoryVulnerability.objects.create(advisory=notice, cve_id="CVE-2021-44228")
    assert any("portfolio-wide status" in problem for problem in validate_publishable(notice))


def test_notice_without_vulnerabilities_is_publishable(notice) -> None:
    """An infrastructure incident update names no CVE and no product."""
    assert notice.vulnerabilities.count() == 0
    assert notice.products.count() == 0
    assert validate_publishable(notice) == []


def test_notice_with_portfolio_status_is_publishable(notice) -> None:
    vuln = AdvisoryVulnerability.objects.create(advisory=notice, cve_id="CVE-2021-44228")
    AdvisoryProductStatus.objects.create(
        vulnerability=vuln,
        status=AdvisoryProductStatus.Status.NOT_AFFECTED,
        justification=AdvisoryProductStatus.Justification.CODE_NOT_PRESENT,
    )
    assert validate_publishable(notice) == []


def test_every_product_needs_a_status(advisory, advisory_product, vulnerability, product, team) -> None:
    second = Product.objects.create(name="Acme Relay", team=team)
    AdvisoryProduct.objects.create(advisory=advisory, product=second)
    AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        advisory_product=advisory_product,
        status=AdvisoryProductStatus.Status.EXPLOITABLE,
        action_statement="Upgrade.",
    )
    assert any("no status for Acme Relay" in problem for problem in validate_publishable(advisory))


def test_fixed_status_must_name_a_fixed_version(advisory, advisory_product, vulnerability) -> None:
    AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        advisory_product=advisory_product,
        status=AdvisoryProductStatus.Status.RESOLVED,
    )
    assert any("names no fixed version" in problem for problem in validate_publishable(advisory))


def test_fixed_status_satisfied_by_a_range(advisory, advisory_product, vulnerability) -> None:
    status = AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        advisory_product=advisory_product,
        status=AdvisoryProductStatus.Status.RESOLVED,
    )
    AdvisoryVersionRange.objects.create(product_status=status, introduced="1.2.0", fixed="1.4.3")
    assert validate_publishable(advisory) == []


def test_not_affected_needs_a_justification_or_impact(advisory, advisory_product, vulnerability) -> None:
    AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        advisory_product=advisory_product,
        status=AdvisoryProductStatus.Status.NOT_AFFECTED,
    )
    assert any("without a justification" in problem for problem in validate_publishable(advisory))


def test_impact_statement_alone_satisfies_not_affected(advisory, advisory_product, vulnerability) -> None:
    AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        advisory_product=advisory_product,
        status=AdvisoryProductStatus.Status.NOT_AFFECTED,
        impact_statement="The vulnerable parser is compiled out.",
    )
    assert validate_publishable(advisory) == []


def test_affected_must_tell_users_what_to_do(advisory, advisory_product, vulnerability) -> None:
    AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        advisory_product=advisory_product,
        status=AdvisoryProductStatus.Status.EXPLOITABLE,
    )
    assert any("tells users nothing to do" in problem for problem in validate_publishable(advisory))


def test_vulnerability_recommendation_satisfies_affected(advisory, advisory_product) -> None:
    vuln = AdvisoryVulnerability.objects.create(
        advisory=advisory, cve_id="CVE-2021-44228", recommendation="Upgrade to 1.4.3."
    )
    AdvisoryProductStatus.objects.create(
        vulnerability=vuln,
        advisory_product=advisory_product,
        status=AdvisoryProductStatus.Status.EXPLOITABLE,
    )
    assert validate_publishable(advisory) == []


def test_publish_validation_query_count_does_not_grow_with_the_graph(
    advisory, advisory_product, team, django_assert_max_num_queries
) -> None:
    """Validation prefetches the status graph, so more products and vulnerabilities
    do not each cost their own queries."""
    products = [advisory_product]
    for name in ("Acme Relay", "Acme Edge", "Acme Core"):
        product = Product.objects.create(name=name, team=team)
        products.append(AdvisoryProduct.objects.create(advisory=advisory, product=product))

    for index in range(4):
        vuln = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id=f"CVE-2026-100{index}")
        for product_link in products:
            status = AdvisoryProductStatus.objects.create(
                vulnerability=vuln,
                advisory_product=product_link,
                status=AdvisoryProductStatus.Status.RESOLVED,
            )
            AdvisoryVersionRange.objects.create(product_status=status, introduced="1.0.0", fixed="1.4.3")

    # 16 statuses and 16 ranges: products, vulnerabilities, statuses, ranges.
    with django_assert_max_num_queries(6):
        assert validate_publishable(advisory) == []


def test_advisory_without_a_title_is_not_publishable(make_publishable) -> None:
    make_publishable.title = "   "
    assert "The advisory needs a title." in validate_publishable(make_publishable)


# --- deletion semantics --------------------------------------------------------


def test_deleting_the_advisory_cascades_the_aggregate(make_publishable, vulnerability, advisory_product) -> None:
    AdvisoryEvent.objects.create(advisory=make_publishable, event_type=AdvisoryEvent.EventType.UPDATE, body="Hi.")
    AdvisoryReference.objects.create(advisory=make_publishable, external_id="CVE-2021-44228")
    make_publishable.delete()

    assert AdvisoryVulnerability.objects.count() == 0
    assert AdvisoryProduct.objects.count() == 0
    assert AdvisoryProductStatus.objects.count() == 0
    assert AdvisoryEvent.objects.count() == 0
    assert AdvisoryReference.objects.count() == 0


def test_deleting_the_team_cascades_advisories(other_team) -> None:
    doomed = SecurityAdvisory.objects.create(team=other_team, title="Goes with the workspace")
    AdvisoryVulnerability.objects.create(advisory=doomed, cve_id="CVE-2021-44228")
    other_team.delete()
    assert SecurityAdvisory.objects.filter(pk=doomed.pk).count() == 0
    assert AdvisoryVulnerability.objects.count() == 0


def test_deleting_the_actor_keeps_the_advisory_and_its_events(advisory) -> None:
    """Provenance is best-effort: losing the user must not erase the record."""
    from django.contrib.auth import get_user_model

    # A throwaway user: deleting the shared ``sample_user`` fixture inside a test
    # collides with its own teardown.
    author = get_user_model().objects.create_user(username="advisory-author", password="x")  # nosec B106
    advisory.created_by = author
    advisory.save()
    event = AdvisoryEvent.objects.create(
        advisory=advisory, event_type=AdvisoryEvent.EventType.UPDATE, body="Investigating.", actor=author
    )

    author.delete()

    advisory.refresh_from_db()
    event.refresh_from_db()
    assert advisory.created_by_id is None
    assert event.actor_id is None
    assert event.body == "Investigating."


def test_deleting_the_source_vex_keeps_the_status(vulnerability, team) -> None:
    component = Component.objects.create(name="gateway", team=team)
    vex = SBOM.objects.create(name="gateway-vex", component=component, format="cyclonedx", bom_type=SBOM.BomType.VEX)
    status = AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability, source=AdvisoryProductStatus.Source.VEX_IMPORT, source_vex=vex
    )
    vex.delete()
    status.refresh_from_db()
    assert status.source_vex_id is None
    assert status.source == AdvisoryProductStatus.Source.VEX_IMPORT

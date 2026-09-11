"""What earns a certification badge, and what does not.

Every test here is a way a badge could claim something the workspace has not
actually published, because that is the only failure mode that matters: a trust
center that overstates a certification is worse than one that shows none.
"""

from __future__ import annotations

import pytest

from sbomify.apps.core.models import Component
from sbomify.apps.documents.models import Document
from sbomify.apps.documents.services.trust_center_badges import public_certification_badges
from sbomify.apps.teams.models import Team


@pytest.fixture
def public_team() -> Team:
    return Team.objects.create(name="Badge Workspace", is_public=True)


def _component(
    team: Team,
    name: str = "ISO 27001",
    *,
    is_global: bool = True,
    visibility: str = Component.Visibility.PUBLIC,
) -> Component:
    return Component.objects.create(
        name=name,
        team=team,
        component_type=Component.ComponentType.DOCUMENT,
        visibility=visibility,
        is_global=is_global,
    )


def _document(
    component: Component,
    *,
    subcategory: str | None = Document.ComplianceSubcategory.ISO27001,
    document_type: str = Document.DocumentType.COMPLIANCE,
    filename: str = "iso27001.pdf",
    name: str = "ISO 27001 certificate",
    version: str = "2026",
) -> Document:
    return Document.objects.create(
        name=name,
        version=version,
        component=component,
        document_type=document_type,
        compliance_subcategory=subcategory,
        document_filename=filename,
    )


@pytest.mark.django_db
def test_a_published_company_wide_report_earns_its_badge(public_team: Team) -> None:
    component = _component(public_team)
    _document(component)

    badges = public_certification_badges(public_team)

    assert [badge["label"] for badge in badges] == ["ISO 27001"]
    assert badges[0]["component_id"] == component.id
    assert badges[0]["image"].endswith("iso-27001.svg")
    assert badges[0]["note"] == ""


@pytest.mark.django_db
def test_a_component_with_no_file_on_it_claims_nothing(public_team: Team) -> None:
    """The easy way to claim a certification you do not hold."""
    _document(_component(public_team), filename="")

    assert public_certification_badges(public_team) == []


@pytest.mark.django_db
def test_a_product_level_report_is_not_a_company_certification(public_team: Team) -> None:
    _document(_component(public_team, is_global=False))

    assert public_certification_badges(public_team) == []


@pytest.mark.django_db
def test_a_private_component_stays_off_the_trust_center(public_team: Team) -> None:
    _document(_component(public_team, visibility=Component.Visibility.PRIVATE))

    assert public_certification_badges(public_team) == []


@pytest.mark.django_db
def test_a_gated_report_still_earns_the_badge(public_team: Team) -> None:
    """The gate is on the download, not on the fact that the workspace holds it."""
    _document(_component(public_team, visibility=Component.Visibility.GATED))

    badges = public_certification_badges(public_team)

    assert [badge["label"] for badge in badges] == ["ISO 27001"]
    assert badges[0]["note"] == "Report available on request"


@pytest.mark.django_db
def test_an_nda_is_not_a_certification(public_team: Team) -> None:
    _document(
        _component(public_team, name="Company NDA"),
        subcategory=Document.ComplianceSubcategory.NDA,
        filename="nda.pdf",
    )

    assert public_certification_badges(public_team) == []


@pytest.mark.django_db
def test_a_compliance_document_with_no_subcategory_earns_nothing(public_team: Team) -> None:
    _document(_component(public_team), subcategory=None)

    assert public_certification_badges(public_team) == []


@pytest.mark.django_db
def test_a_non_compliance_document_earns_nothing(public_team: Team) -> None:
    """document_type and subcategory are stored separately, so both are checked."""
    _document(_component(public_team), document_type=Document.DocumentType.REPORT)

    assert public_certification_badges(public_team) == []


@pytest.mark.django_db
def test_soc2_type_i_and_type_ii_are_separate_badges(public_team: Team) -> None:
    _document(
        _component(public_team, name="SOC 2 Type I"),
        subcategory=Document.ComplianceSubcategory.SOC2_TYPE1,
        filename="soc2-type1.pdf",
    )
    _document(
        _component(public_team, name="SOC 2 Type II"),
        subcategory=Document.ComplianceSubcategory.SOC2_TYPE2,
        filename="soc2-type2.pdf",
    )

    badges = public_certification_badges(public_team)

    # Catalogue order: the strongest assurance reads first.
    assert [badge["label"] for badge in badges] == ["SOC 2 Type II", "SOC 2 Type I"]


@pytest.mark.django_db
def test_cra_conformity_earns_its_badge(public_team: Team) -> None:
    """A declared conformity is a different claim from an audit, published the same way."""
    _document(
        _component(public_team, name="CRA conformity"),
        subcategory=Document.ComplianceSubcategory.CRA,
        filename="cra-declaration-of-conformity.pdf",
    )

    badges = public_certification_badges(public_team)

    assert [badge["label"] for badge in badges] == ["CRA"]
    assert badges[0]["image"].endswith("cra.svg")


@pytest.mark.django_db
def test_a_certification_with_no_seal_still_badges(public_team: Team) -> None:
    """Undifferentiated SOC 2 has no artwork; the tile draws the label instead."""
    _document(
        _component(public_team, name="SOC 2"),
        subcategory=Document.ComplianceSubcategory.SOC2,
        filename="soc2-report.pdf",
    )

    badges = public_certification_badges(public_team)

    assert [badge["label"] for badge in badges] == ["SOC 2"]
    # Empty, not the static root: "{% static %}" of an empty path renders a
    # broken image because the root is a truthy string.
    assert badges[0]["image"] == ""


@pytest.mark.django_db
def test_every_year_of_a_report_shows_one_badge_pointing_at_the_newest(public_team: Team) -> None:
    older = _component(public_team, name="ISO 27001 2025")
    _document(older, version="2025")
    newer = _component(public_team, name="ISO 27001 2026")
    _document(newer, version="2026")

    badges = public_certification_badges(public_team)

    assert len(badges) == 1
    assert badges[0]["component_id"] == newer.id
    assert badges[0]["version"] == "2026"


@pytest.mark.django_db
def test_another_workspace_report_does_not_leak(public_team: Team) -> None:
    other = Team.objects.create(name="Other Workspace", is_public=True)
    _document(_component(other))

    assert public_certification_badges(public_team) == []


@pytest.mark.django_db
def test_the_catalogue_covers_every_badgeable_subcategory() -> None:
    """NDA is the only compliance subcategory that is deliberately not a badge.

    A subcategory added to the model without a catalogue entry would be silently
    unbadgeable, which is the quiet way this feature stops working.
    """
    from sbomify.apps.documents.services.trust_center_badges import BADGE_CATALOGUE

    expected = {value for value, _ in Document.ComplianceSubcategory.choices} - {Document.ComplianceSubcategory.NDA}

    assert set(BADGE_CATALOGUE) == expected

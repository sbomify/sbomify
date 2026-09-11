"""What earns a certification badge, and what does not.

Every test here is a way a badge could claim something the workspace has not
actually published, because that is the only failure mode that matters: a trust
center that overstates a certification is worse than one that shows none.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

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
    """An NDA is published the same way and still earns nothing.

    It is `DocumentType.NDA` rather than a compliance document now, so the
    badge query excludes it by type instead of by a carve-out. Worth keeping as
    a test: the NDA sits on the same company-wide published component as the
    certifications, so a query that widened by mistake would pick it up.
    """
    _document(
        _component(public_team, name="Company NDA"),
        document_type=Document.DocumentType.NDA,
        subcategory=None,
        filename="nda.pdf",
        name="Mutual non-disclosure agreement",
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
def test_the_migration_moves_plain_soc2_to_type_ii(public_team: Team) -> None:
    """The data move runs under --nomigrations, where the migration never does.

    Tests build a bare schema, so nothing else in the suite executes 0015. The
    function is called directly against a real table instead, with a stub
    registry standing in for the historical model, which is the same shape the
    migration gets.
    """
    # importlib because a migration module name starts with a digit.
    migration = import_module("sbomify.apps.documents.migrations.0015_certification_subcategories")

    plain = _document(_component(public_team, name="SOC 2"), subcategory="soc2", filename="soc2-report.pdf")
    iso = _document(_component(public_team))

    class _Registry:
        @staticmethod
        def get_model(app_label: str, model_name: str) -> type[Document]:
            return Document

    migration.move_plain_soc2_to_type_ii(_Registry(), None)

    plain.refresh_from_db()
    iso.refresh_from_db()
    assert plain.compliance_subcategory == Document.ComplianceSubcategory.SOC2_TYPE2
    assert iso.compliance_subcategory == Document.ComplianceSubcategory.ISO27001


def test_every_badge_names_a_seal_that_exists() -> None:
    """An entry with no artwork renders a broken image, not a fallback.

    ``static("")`` returns the static root, which is a truthy string, so a
    seal-less entry would ship as a broken image on a customer's trust center.
    Catching it here costs one assertion.
    """
    from django.conf import settings

    from sbomify.apps.documents.services.trust_center_badges import BADGE_CATALOGUE

    static_root = Path(settings.BASE_DIR) / "sbomify" / "static"
    missing = {
        key: meta["image"] for key, meta in BADGE_CATALOGUE.items() if not (static_root / meta["image"]).is_file()
    }

    assert not missing, f"badge seals that do not exist: {missing}"


@pytest.mark.django_db
def test_the_catalogue_covers_every_badgeable_subcategory() -> None:
    """Every compliance subcategory is a badge, with no exceptions left.

    NDA used to be the one carve-out; it is its own document type now, so the
    catalogue and the enum should agree exactly. A subcategory added to the
    model without a catalogue entry would be silently unbadgeable, which is the
    quiet way this feature stops working.
    """
    from sbomify.apps.documents.services.trust_center_badges import BADGE_CATALOGUE

    assert set(BADGE_CATALOGUE) == {value for value, _ in Document.ComplianceSubcategory.choices}


def test_the_demo_seed_publishes_a_certification_that_earns_a_badge() -> None:
    """The seeded workspace is where this feature gets looked at.

    Its global "Certifications" component carried an ISO 27001 document with no
    subcategory, so the demo trust center had the component, the file and the
    catalogue name and still showed nothing. The seed spec now names the
    subcategory, and this fails if a later edit drops it.
    """
    from sbomify.apps.core.management.commands.seed_demo_data import GLOBAL_COMPONENTS
    from sbomify.apps.documents.services.trust_center_badges import BADGE_CATALOGUE

    badgeable = {
        subcategory
        for spec in GLOBAL_COMPONENTS
        if spec.visibility != Component.Visibility.PRIVATE
        for _, doc_type, _, subcategory in spec.documents
        if doc_type == Document.DocumentType.COMPLIANCE and subcategory in BADGE_CATALOGUE
    }

    assert Document.ComplianceSubcategory.ISO27001 in badgeable


@pytest.mark.django_db
def test_re_seeding_tags_a_certificate_seeded_before_subcategories(public_team: Team, mocker: MockerFixture) -> None:
    """A demo database seeded earlier keeps its rows, so the tag has to catch up.

    ``_ensure_document`` returns early on an existing name/version, which would
    leave the ISO certificate from an older seed untagged and unbadgeable no
    matter how often the seed is re-run.
    """
    from sbomify.apps.core.management.commands.seed_demo_data import Command, Counts

    mocker.patch(
        "sbomify.apps.core.management.commands.seed_demo_data.StorageClient"
    ).return_value.upload_document.return_value = "seeded.md"

    component = _component(public_team, name="Certifications")
    stale = Document.objects.create(
        name="ISO 27001 certificate",
        version="2026",
        document_filename="seeded.md",
        component=component,
        source="seed_demo_data",
        content_type="text/markdown",
        file_size=7,
        document_type=Document.DocumentType.COMPLIANCE,
        compliance_subcategory=None,
    )

    Command()._ensure_document(
        public_team,
        component,
        "ISO 27001 certificate",
        Document.DocumentType.COMPLIANCE,
        "2026",
        Document.ComplianceSubcategory.ISO27001,
        Counts(),
    )

    stale.refresh_from_db()
    assert stale.compliance_subcategory == Document.ComplianceSubcategory.ISO27001
    assert [badge["label"] for badge in public_certification_badges(public_team)] == ["ISO 27001"]


@pytest.mark.django_db
def test_an_nda_is_recognised_by_its_type_alone(public_team: Team) -> None:
    """``is_nda`` is a single-field check now, and nothing else answers to it.

    The gated-access path turns on this predicate, so the split is only safe if
    a moved NDA still reports as one and a certification never does.
    """
    component = _component(public_team, name="Company NDA")
    nda = _document(
        component,
        document_type=Document.DocumentType.NDA,
        subcategory=None,
        filename="nda.pdf",
        name="Mutual non-disclosure agreement",
    )
    certification = _document(_component(public_team))

    assert nda.is_nda()
    assert not nda.is_compliance_document()
    assert not certification.is_nda()
    assert certification.is_compliance_document()


@pytest.mark.django_db
def test_the_migration_moves_the_nda_out_of_compliance_and_back(public_team: Team) -> None:
    """The data move runs under ``--nomigrations``, where the migration never does.

    Tests build a bare schema, so nothing else in the suite executes 0016. The
    reverse is exercised too, because unlike 0015 this one genuinely inverts:
    after the forward pass an ``nda`` row is exactly a row it moved.
    """
    migration = import_module("sbomify.apps.documents.migrations.0016_nda_document_type")

    component = _component(public_team, name="Company NDA")
    nda = Document.objects.create(
        name="Mutual non-disclosure agreement",
        version="2026.1",
        component=component,
        document_type=Document.DocumentType.COMPLIANCE,
        compliance_subcategory="nda",
        document_filename="nda.pdf",
    )
    certification = _document(_component(public_team))

    class _Registry:
        @staticmethod
        def get_model(app_label: str, model_name: str) -> type[Document]:
            return Document

    migration.move_nda_out_of_compliance(_Registry(), None)

    nda.refresh_from_db()
    certification.refresh_from_db()
    assert nda.document_type == Document.DocumentType.NDA
    assert nda.compliance_subcategory is None
    # The certification is left exactly where it was.
    assert certification.document_type == Document.DocumentType.COMPLIANCE
    assert certification.compliance_subcategory == Document.ComplianceSubcategory.ISO27001

    migration.move_nda_back_into_compliance(_Registry(), None)

    nda.refresh_from_db()
    assert nda.document_type == Document.DocumentType.COMPLIANCE
    assert nda.compliance_subcategory == "nda"

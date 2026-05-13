"""Tests for OSCAL service — catalog loading, import, assessment, serialization."""

from __future__ import annotations

import json

import pytest

from sbomify.apps.compliance.models import (
    OSCALAssessmentResult,
    OSCALCatalog,
    OSCALControl,
    OSCALFinding,
)
from sbomify.apps.compliance.services.oscal_service import (
    build_trestle_assessment_results,
    create_assessment_result,
    ensure_cra_catalog,
    import_catalog_to_db,
    load_cra_catalog,
    serialize_assessment_results,
    update_finding,
)
from sbomify.apps.core.models import Product


@pytest.fixture
def product(sample_team_with_owner_member):
    """Create a Product for testing."""
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="Test Product", team=team)


class TestLoadCraCatalog:
    def test_loads_valid_trestle_catalog(self):
        catalog = load_cra_catalog()

        assert catalog.uuid is not None
        assert catalog.metadata.title == "EU CRA Annex I \u2014 Essential Cybersecurity Requirements"
        assert catalog.metadata.version == "1.1.0"
        assert len(catalog.groups) == 5

    def test_has_21_controls_across_5_groups(self):
        catalog = load_cra_catalog()

        total = sum(len(g.controls) for g in catalog.groups)
        assert total == 21

    def test_group_distribution(self):
        catalog = load_cra_catalog()

        group_counts = {g.id: len(g.controls) for g in catalog.groups}
        assert group_counts == {
            "cra-sd": 6,
            "cra-dp": 4,
            "cra-av": 2,
            "cra-mn": 1,
            "cra-vh": 8,
        }

    def test_controls_have_required_fields(self):
        catalog = load_cra_catalog()

        for group in catalog.groups:
            for control in group.controls:
                assert control.id is not None
                assert control.title is not None
                assert control.props is not None
                assert len(control.props) >= 2
                prop_names = {p.name for p in control.props}
                assert "annex-ref" in prop_names
                assert "label" in prop_names
                assert control.parts is not None
                # At least a statement part
                part_names = {p.name for p in control.parts}
                assert "statement" in part_names


@pytest.mark.django_db
class TestImportCatalogToDb:
    def test_creates_catalog_and_controls(self):
        trestle_catalog = load_cra_catalog()
        db_catalog = import_catalog_to_db(trestle_catalog, "EU CRA Annex I", "1.0.0")

        assert db_catalog.pk is not None
        assert db_catalog.name == "EU CRA Annex I"
        assert db_catalog.version == "1.0.0"
        assert db_catalog.catalog_json is not None

        controls = OSCALControl.objects.filter(catalog=db_catalog)
        assert controls.count() == 21

    def test_group_distribution_in_db(self):
        trestle_catalog = load_cra_catalog()
        db_catalog = import_catalog_to_db(trestle_catalog, "EU CRA Annex I", "1.0.0")

        sd = OSCALControl.objects.filter(catalog=db_catalog, group_id="cra-sd").count()
        dp = OSCALControl.objects.filter(catalog=db_catalog, group_id="cra-dp").count()
        av = OSCALControl.objects.filter(catalog=db_catalog, group_id="cra-av").count()
        mn = OSCALControl.objects.filter(catalog=db_catalog, group_id="cra-mn").count()
        vh = OSCALControl.objects.filter(catalog=db_catalog, group_id="cra-vh").count()

        assert sd == 6
        assert dp == 4
        assert av == 2
        assert mn == 1
        assert vh == 8

    def test_controls_have_descriptions(self):
        trestle_catalog = load_cra_catalog()
        db_catalog = import_catalog_to_db(trestle_catalog, "EU CRA Annex I", "1.0.0")

        controls = OSCALControl.objects.filter(catalog=db_catalog)
        for control in controls:
            assert control.description, f"Control {control.control_id} should have a description"

    def test_sort_order_is_sequential(self):
        trestle_catalog = load_cra_catalog()
        db_catalog = import_catalog_to_db(trestle_catalog, "EU CRA Annex I", "1.0.0")

        controls = list(OSCALControl.objects.filter(catalog=db_catalog).order_by("sort_order"))
        for i, control in enumerate(controls):
            assert control.sort_order == i

    def test_import_marks_vh_controls_mandatory_part_ii(self):
        """CRA Art 13(4) + FAQ 4.1.3: Part II (vulnerability handling,
        ``group_id='cra-vh'``) controls must be always-mandatory and
        flagged ``annex_part='part-ii'``. Every non-VH control must be
        Part I (risk-based, N/A allowed with justification).

        This is the contract ``update_finding`` relies on — a regression
        where the import leaves Part II rows with ``is_mandatory=False``
        would let operators mark vulnerability-handling controls as N/A,
        producing a legally invalid DoC.
        """
        trestle_catalog = load_cra_catalog()
        db_catalog = import_catalog_to_db(trestle_catalog, "EU CRA Annex I", "1.1.0")

        vh = OSCALControl.objects.filter(catalog=db_catalog, group_id="cra-vh")
        assert vh.exists(), "expected at least one cra-vh control"
        for c in vh:
            assert c.is_mandatory is True, f"{c.control_id} Part II must be mandatory"
            assert c.annex_part == "part-ii", f"{c.control_id} expected part-ii, got {c.annex_part}"

        non_vh = OSCALControl.objects.filter(catalog=db_catalog).exclude(group_id="cra-vh")
        for c in non_vh:
            assert c.is_mandatory is False, f"{c.control_id} Part I must not be mandatory"
            assert c.annex_part == "part-i", f"{c.control_id} expected part-i, got {c.annex_part}"


@pytest.mark.django_db
class TestEnsureCraCatalog:
    def test_creates_catalog_on_first_call(self):
        catalog = ensure_cra_catalog()

        assert catalog.pk is not None
        assert catalog.name == "EU CRA Annex I"
        assert catalog.version == "1.1.0"
        assert OSCALControl.objects.filter(catalog=catalog).count() == 21

    def test_idempotent_returns_same_catalog(self):
        catalog1 = ensure_cra_catalog()
        catalog2 = ensure_cra_catalog()

        assert catalog1.pk == catalog2.pk
        assert OSCALCatalog.objects.filter(name="EU CRA Annex I", version="1.1.0").count() == 1

    def test_import_rejects_unknown_annex_part(self):
        """A catalog JSON typo like ``part-iii`` used to slip through
        the ``bulk_create`` path because ``choices`` is not enforced on
        the write path. ``import_catalog_to_db`` now validates the
        value explicitly and fails the import; the DB constraint (0012)
        is the backstop for anyone who reaches past the service layer.

        Duck-types the trestle catalog with ``types.SimpleNamespace``
        to avoid wiring up a full trestle ``Catalog`` (which requires
        metadata fields whose import surface differs across trestle
        versions). ``import_catalog_to_db`` only reads ``groups`` +
        each group's ``id``/``title``/``controls`` + each control's
        ``id``/``title``/``parts``/``props``, so the simplified shape
        is enough to exercise the ``annex-part`` validator.
        """
        from types import SimpleNamespace
        from unittest.mock import patch

        bad_control = SimpleNamespace(
            id="cra-bad-1",
            title="Bad control",
            parts=[SimpleNamespace(name="statement", prose="description")],
            props=[SimpleNamespace(name="annex-part", value="part-iii")],
        )
        bad_group = SimpleNamespace(
            id="cra-sd", title="Security by Design", controls=[bad_control]
        )
        bad_catalog = SimpleNamespace(
            groups=[bad_group],
            oscal_serialize_json=lambda: '{"groups": []}',
        )

        # Patch trestle-JSON round-trip so the OSCALCatalog row save
        # doesn't try to parse the stubbed payload.
        with patch("json.loads", return_value={"groups": []}):
            with pytest.raises(ValueError, match=r"(?i)annex-part"):
                import_catalog_to_db(bad_catalog, "Broken CRA", "99.0")

    def test_is_mandatory_biconditional_invariant(self):
        """Every control row must satisfy ``is_mandatory == (annex_part
        == "part-ii")``. The rule is encoded across four code paths
        (schema import, migration 0007 backfill, ``update_finding``
        gate, Alpine badge) — a desync between any two silently opens
        a Part II control to N/A. Enforce the biconditional as a
        post-condition on every import."""
        catalog = ensure_cra_catalog()
        for control in OSCALControl.objects.filter(catalog=catalog):
            assert control.is_mandatory == (control.annex_part == "part-ii"), (
                f"control {control.control_id} violates the biconditional: "
                f"annex_part={control.annex_part!r} is_mandatory={control.is_mandatory!r}"
            )


@pytest.mark.django_db
class TestCreateAssessmentResult:
    def test_creates_ar_with_21_unanswered_findings(self, sample_team_with_owner_member, sample_user, product):
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team

        ar = create_assessment_result(catalog, team, product, sample_user)

        assert ar.pk is not None
        assert ar.catalog == catalog
        assert ar.team == team
        assert "Test Product" in ar.title
        assert ar.status == OSCALAssessmentResult.AssessmentStatus.IN_PROGRESS

        findings = OSCALFinding.objects.filter(assessment_result=ar)
        assert findings.count() == 21
        assert all(f.status == OSCALFinding.FindingStatus.UNANSWERED for f in findings)


@pytest.mark.django_db
class TestUpdateFinding:
    def test_updates_status_and_notes(self, sample_team_with_owner_member, sample_user, product):
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        finding = OSCALFinding.objects.filter(assessment_result=ar).first()
        assert finding is not None

        updated = update_finding(finding, "satisfied", "Fully implemented.")

        assert updated.status == "satisfied"
        assert updated.notes == "Fully implemented."

        # Verify persisted
        finding.refresh_from_db()
        assert finding.status == "satisfied"
        assert finding.notes == "Fully implemented."

    def test_rejects_invalid_status(self, sample_team_with_owner_member, sample_user, product):
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        finding = OSCALFinding.objects.filter(assessment_result=ar).first()
        assert finding is not None

        with pytest.raises(ValueError, match="Invalid status"):
            update_finding(finding, "bogus-status")

    def test_rejects_not_applicable_for_part_ii_control(self, sample_team_with_owner_member, sample_user, product):
        """Part II (vulnerability handling) controls cannot be marked not-applicable (CRA Art 13(4))."""
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        # Find a Part II (mandatory) control
        finding = OSCALFinding.objects.filter(assessment_result=ar, control__is_mandatory=True).first()
        assert finding is not None

        with pytest.raises(ValueError, match="always mandatory"):
            update_finding(finding, "not-applicable", justification="Some justification")

    def test_rejects_not_applicable_reads_is_mandatory_not_group_id(
        self, sample_team_with_owner_member, sample_user, product
    ):
        """Regression seal: the Part II gate must key off the
        ``control.is_mandatory`` column, NOT the ``group_id`` string.
        If a future catalog import (notified-body clone, localised
        variant) uses a different group-id convention, the gate must
        still hold when ``is_mandatory=True``.
        """
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        # Take any control, mutate its group_id to something
        # unexpected, and confirm the gate still fires purely from
        # is_mandatory.
        finding = OSCALFinding.objects.filter(assessment_result=ar, control__is_mandatory=True).first()
        assert finding is not None
        finding.control.group_id = "totally-not-cra-vh"
        finding.control.save(update_fields=["group_id"])
        finding.refresh_from_db()

        with pytest.raises(ValueError, match="always mandatory"):
            update_finding(finding, "not-applicable", justification="x")

    def test_rejects_not_applicable_without_justification_for_part_i(
        self, sample_team_with_owner_member, sample_user, product
    ):
        """Part I controls marked not-applicable require justification (CRA Art 13(4))."""
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        # Find a Part I (non-mandatory) control
        finding = OSCALFinding.objects.filter(assessment_result=ar, control__is_mandatory=False).first()
        assert finding is not None

        with pytest.raises(ValueError, match="requires a clear justification"):
            update_finding(finding, "not-applicable")

    def test_allows_not_applicable_with_justification_for_part_i(
        self, sample_team_with_owner_member, sample_user, product
    ):
        """Part I controls can be marked not-applicable with proper justification."""
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        finding = OSCALFinding.objects.filter(assessment_result=ar, control__is_mandatory=False).first()
        assert finding is not None

        updated = update_finding(finding, "not-applicable", justification="Not applicable to this product type")
        assert updated.status == "not-applicable"
        assert updated.justification == "Not applicable to this product type"

    def test_accepts_unanswered_status(self, sample_team_with_owner_member, sample_user, product):
        """Step 3 notes autosave needs to PUT the current (potentially
        ``unanswered``) status alongside the typed notes. Reject here
        would force the UI to require a terminal status before any
        note can be persisted."""
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)
        finding = OSCALFinding.objects.filter(assessment_result=ar).first()
        assert finding is not None

        updated = update_finding(finding, "unanswered", notes="Work-in-progress note", justification="")
        assert updated.status == "unanswered"
        assert updated.notes == "Work-in-progress note"

    def test_audit_log_uses_cra_assessment_id(self, sample_team_with_owner_member, sample_user, product):
        """Audit events across event types must share the same
        ``assessment_id`` key so downstream consumers can correlate a
        ``cra.finding.update`` with the ``cra.assessment.step_save``
        that follows. Log the ``CRAAssessment`` PK, not the
        ``OSCALAssessmentResult`` PK.
        """
        import logging

        from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment

        team = sample_team_with_owner_member.team
        assessment_result = get_or_create_assessment(product.id, sample_user, team)
        assert assessment_result.ok
        assessment = assessment_result.value
        assert assessment is not None

        finding = OSCALFinding.objects.filter(
            assessment_result=assessment.oscal_assessment_result,
            control__is_mandatory=False,
        ).first()
        assert finding is not None

        records: list[logging.LogRecord] = []

        class _ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _ListHandler(level=logging.INFO)
        audit_logger = logging.getLogger("sbomify.compliance.audit")
        audit_logger.addHandler(handler)
        try:
            update_finding(finding, "satisfied", notes="", justification="", actor=sample_user)
        finally:
            audit_logger.removeHandler(handler)

        assert records
        event = records[-1]
        # CRAAssessment PK, not the OSCAL AR PK.
        assert getattr(event, "assessment_id", None) == assessment.pk
        assert getattr(event, "assessment_id", None) != str(finding.assessment_result_id)

    def test_emits_audit_log_on_status_change(self, sample_team_with_owner_member, sample_user, product):
        """CRA non-repudiation: every finding state change must leave
        a durable trail of who/when/before/after. Without this a
        regulator asking ``who marked control ACM-1 as not-applicable
        on day X`` has no way to answer.

        Uses a ``MemoryHandler`` installed directly on the audit logger
        because the app-wide ``sbomify`` logger has ``propagate=False``
        in settings, so pytest's ``caplog`` (which attaches to root)
        never sees audit records.
        """
        import logging

        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)
        finding = OSCALFinding.objects.filter(
            assessment_result=ar, control__is_mandatory=False
        ).first()
        assert finding is not None

        records: list[logging.LogRecord] = []

        class _ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _ListHandler(level=logging.INFO)
        audit_logger = logging.getLogger("sbomify.compliance.audit")
        audit_logger.addHandler(handler)
        try:
            update_finding(
                finding,
                "satisfied",
                "Measured compliance in Q2 audit",
                "",
                actor=sample_user,
            )
        finally:
            audit_logger.removeHandler(handler)

        assert records, "expected at least one audit record"
        event = records[-1]
        rendered = event.getMessage()
        assert rendered.startswith("cra.finding.update")
        # The structured payload must be embedded in the message text
        # so production log formatters that only render %(message)s
        # still capture the audit context.
        assert '"user_id"' in rendered
        assert '"delta"' in rendered
        assert getattr(event, "user_id", None) == sample_user.id
        assert "status" in getattr(event, "delta", {})


@pytest.mark.django_db
class TestAnnexPartBackfillRemediation:
    """Regression for the 0007 data migration: legacy findings that
    were marked ``not-applicable`` against controls later classified as
    Part II (``is_mandatory=True``) must be reset to ``unanswered`` so
    the operator re-evaluates them. CRA Art 13(4) disallows marking
    vulnerability-handling controls as N/A, so silently carrying the
    legacy state forward across the upgrade would export a non-
    compliant DoC.
    """

    def test_backfill_resets_na_findings_on_now_mandatory_controls(
        self, sample_team_with_owner_member, sample_user, product
    ):
        import importlib

        from django.apps import apps as django_apps

        migration = importlib.import_module(
            "sbomify.apps.compliance.migrations.0007_backfill_oscal_control_annex_part"
        )
        backfill_annex_part = migration.backfill_annex_part

        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team

        # Seed a legacy state: Part II control marked as N/A, Part I
        # control also marked as N/A (the latter must stay untouched).
        ar = create_assessment_result(catalog, team, product, sample_user)
        part_ii_ctl = OSCALControl.objects.filter(catalog=catalog, group_id="cra-vh").first()
        part_i_ctl = OSCALControl.objects.filter(catalog=catalog).exclude(group_id="cra-vh").first()
        assert part_ii_ctl is not None and part_i_ctl is not None
        OSCALFinding.objects.filter(
            assessment_result=ar, control=part_ii_ctl
        ).update(status="not-applicable")
        OSCALFinding.objects.filter(
            assessment_result=ar, control=part_i_ctl
        ).update(status="not-applicable", justification="Not applicable by design")

        # Simulate the pre-0007 schema state where these fields exist
        # but haven't been populated yet.
        OSCALControl.objects.filter(catalog=catalog).update(
            is_mandatory=False, annex_part="part-i"
        )

        backfill_annex_part(django_apps, schema_editor=None)

        # Part II control now flagged mandatory and its legacy N/A
        # finding is reset to ``unanswered`` so the operator re-evaluates.
        part_ii_ctl.refresh_from_db()
        assert part_ii_ctl.is_mandatory is True
        assert part_ii_ctl.annex_part == "part-ii"
        part_ii_finding = OSCALFinding.objects.get(assessment_result=ar, control=part_ii_ctl)
        assert part_ii_finding.status == "unanswered"

        # Part I control stays Part I and its N/A finding is preserved.
        part_i_ctl.refresh_from_db()
        assert part_i_ctl.is_mandatory is False
        assert part_i_ctl.annex_part == "part-i"
        part_i_finding = OSCALFinding.objects.get(assessment_result=ar, control=part_i_ctl)
        assert part_i_finding.status == "not-applicable"


@pytest.mark.django_db
class TestLegacyEuccRemapMigration:
    """Regression for the 0009 data migration. Pre-existing CRA
    assessments persisted before PR #861 could carry
    ``product_category='critical'`` + ``conformity_assessment_procedure=
    'eucc'``, which the new default mapping no longer permits (CRA
    Art 8(1) — EUCC is not yet mandated). The migration snaps those
    rows to ``module_b_c`` so the next DoC export does not render the
    deprecated procedure; other combinations must be left untouched.
    """

    def test_remap_updates_critical_eucc_and_preserves_others(
        self, sample_team_with_owner_member, sample_user, product
    ):
        import importlib

        from django.apps import apps as django_apps

        from sbomify.apps.compliance.models import CRAAssessment
        from sbomify.apps.compliance.services.wizard_service import (
            get_or_create_assessment,
        )

        team = sample_team_with_owner_member.team

        def _assessment(product_) -> CRAAssessment:
            r = get_or_create_assessment(product_.id, sample_user, team)
            assert r.ok and r.value is not None
            return r.value

        legacy = _assessment(product)
        legacy.product_category = CRAAssessment.ProductCategory.CRITICAL
        legacy.conformity_assessment_procedure = "eucc"
        legacy.save(update_fields=["product_category", "conformity_assessment_procedure"])

        non_critical_eucc = _assessment(Product.objects.create(name="Other", team=team))
        non_critical_eucc.product_category = CRAAssessment.ProductCategory.DEFAULT
        non_critical_eucc.conformity_assessment_procedure = "eucc"
        non_critical_eucc.save(update_fields=["product_category", "conformity_assessment_procedure"])

        critical_bc = _assessment(Product.objects.create(name="Third", team=team))
        critical_bc.product_category = CRAAssessment.ProductCategory.CRITICAL
        critical_bc.conformity_assessment_procedure = "module_b_c"
        critical_bc.save(update_fields=["product_category", "conformity_assessment_procedure"])

        migration = importlib.import_module(
            "sbomify.apps.compliance.migrations.0009_remap_legacy_critical_eucc"
        )
        migration.remap_critical_eucc(django_apps, schema_editor=None)

        legacy.refresh_from_db()
        non_critical_eucc.refresh_from_db()
        critical_bc.refresh_from_db()

        assert legacy.conformity_assessment_procedure == "module_b_c"
        # Non-critical EUCC is a different policy question — the
        # migration intentionally leaves it alone.
        assert non_critical_eucc.conformity_assessment_procedure == "eucc"
        # Already-permitted critical procedure is untouched.
        assert critical_bc.conformity_assessment_procedure == "module_b_c"


@pytest.mark.django_db
class TestBuildTrestleAssessmentResults:
    def test_produces_valid_oscal(self, sample_team_with_owner_member, sample_user, product):
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        # Set some findings to different statuses for a realistic test
        findings = list(OSCALFinding.objects.filter(assessment_result=ar).order_by("control__sort_order"))
        update_finding(findings[0], "satisfied", "Control implemented")
        update_finding(findings[1], "not-satisfied", "Needs work")
        # findings[2] is a Part I control — justification required for N/A (CRA Art 13(4))
        update_finding(findings[2], "not-applicable", "N/A for this product", justification="Not applicable to this product type")

        trestle_ar = build_trestle_assessment_results(ar)

        assert trestle_ar.uuid is not None
        assert trestle_ar.metadata is not None
        assert len(trestle_ar.results) == 1

        result = trestle_ar.results[0]
        assert result.findings is not None
        assert len(result.findings) == 21
        assert result.reviewed_controls is not None

    def test_status_mapping(self, sample_team_with_owner_member, sample_user, product):
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        findings = list(OSCALFinding.objects.filter(assessment_result=ar).order_by("control__sort_order"))
        update_finding(findings[0], "satisfied")
        update_finding(findings[1], "not-satisfied")
        # findings[2] is Part I — justification required for N/A (CRA Art 13(4))
        update_finding(findings[2], "not-applicable", justification="Incompatible with product nature")
        # findings[3] stays unanswered

        trestle_ar = build_trestle_assessment_results(ar)
        oscal_findings = trestle_ar.results[0].findings

        # Find findings by target_id
        by_target = {f.target.target_id: f for f in oscal_findings}

        sat = by_target[findings[0].control.control_id]
        assert sat.target.status.state.value == "satisfied"

        not_sat = by_target[findings[1].control.control_id]
        assert not_sat.target.status.state.value == "not-satisfied"

        na = by_target[findings[2].control.control_id]
        assert na.target.status.state.value == "satisfied"
        assert any(p.name == "finding-disposition" and p.value == "not-applicable" for p in na.props)

        unanswered = by_target[findings[3].control.control_id]
        assert unanswered.target.status.state.value == "not-satisfied"
        assert any(p.name == "finding-disposition" and p.value == "omitted" for p in unanswered.props)

    def test_roundtrip_serialization(self, sample_team_with_owner_member, sample_user, product):
        """Build trestle AR, serialize, and parse back to verify validity."""
        from trestle.oscal.assessment_results import AssessmentResults

        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        trestle_ar = build_trestle_assessment_results(ar)
        json_str = trestle_ar.oscal_serialize_json()

        # Parse back — trestle serializes with an "assessment-results" wrapper key
        data = json.loads(json_str)
        inner = data.get("assessment-results", data)
        roundtripped = AssessmentResults(**inner)
        assert roundtripped.uuid == trestle_ar.uuid
        assert len(roundtripped.results) == 1
        assert len(roundtripped.results[0].findings) == 21


@pytest.mark.django_db
class TestSerializeAssessmentResults:
    def test_returns_json_string(self, sample_team_with_owner_member, sample_user, product):
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        update_finding(
            OSCALFinding.objects.filter(assessment_result=ar).first(),
            "satisfied",
            "Done",
        )

        json_str = serialize_assessment_results(ar)

        assert isinstance(json_str, str)
        raw = json.loads(json_str)
        # trestle wraps in "assessment-results" key
        data = raw.get("assessment-results", raw)
        assert "uuid" in data
        assert "metadata" in data
        assert "results" in data
        assert len(data["results"]) == 1
        assert len(data["results"][0]["findings"]) == 21

    def test_reflects_correct_statuses(self, sample_team_with_owner_member, sample_user, product):
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        findings = list(OSCALFinding.objects.filter(assessment_result=ar).order_by("control__sort_order"))
        update_finding(findings[0], "satisfied")
        update_finding(findings[1], "not-satisfied")

        json_str = serialize_assessment_results(ar)
        raw = json.loads(json_str)
        data = raw.get("assessment-results", raw)

        oscal_findings = data["results"][0]["findings"]
        by_target = {f["target"]["target-id"]: f for f in oscal_findings}

        sat = by_target[findings[0].control.control_id]
        assert sat["target"]["status"]["state"] == "satisfied"

        not_sat = by_target[findings[1].control.control_id]
        assert not_sat["target"]["status"]["state"] == "not-satisfied"

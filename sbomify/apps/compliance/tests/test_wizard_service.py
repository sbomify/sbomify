"""Tests for the CRA compliance wizard service."""

from __future__ import annotations

import datetime

import pytest

from sbomify.apps.compliance.models import (
    CRAAssessment,
    OSCALAssessmentResult,
    OSCALFinding,
)
from sbomify.apps.compliance.services.wizard_service import (
    get_assessment_by_id,
    get_assessment_list_for_team,
    get_compliance_summary,
    get_or_create_assessment,
    get_step_context,
    save_step_data,
)
from sbomify.apps.core.models import Product
from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact


@pytest.fixture
def product(sample_team_with_owner_member):
    """Create a Product for testing."""
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="CRA Test Product", team=team)


@pytest.fixture
def product_with_contacts(sample_team_with_owner_member, product):
    """Product with manufacturer contact and security contact."""
    team = sample_team_with_owner_member.team
    profile = ContactProfile.objects.create(name="Default Profile", team=team, is_default=True)
    entity = ContactEntity.objects.create(
        profile=profile,
        name="Acme Corp",
        email="info@acme.test",
        address="123 Test St",
        is_manufacturer=True,
        website_urls=["https://acme.test"],
    )
    ContactProfileContact.objects.create(
        entity=entity,
        name="Security Lead",
        email="security@acme.test",
        is_security_contact=True,
    )
    return product


@pytest.fixture
def _valid_manufacturer(sample_team_with_owner_member):
    """Configure a real (non-placeholder) manufacturer for the team.

    Required for Step 1 save-path tests because ``_save_step_1``
    refuses to mark the step complete when the team's manufacturer
    name passes ``is_placeholder_manufacturer`` — the server-side
    mirror of the client-side gate (issue #908). Tests that
    specifically exercise the placeholder refusal should NOT request
    this fixture.
    """
    team = sample_team_with_owner_member.team
    profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
    ContactEntity.objects.create(
        profile=profile,
        name="Acme Labs GmbH",
        email="legal@acmelabs.example",
        is_manufacturer=True,
    )


@pytest.fixture
def assessment(sample_team_with_owner_member, sample_user, product, _valid_manufacturer):
    """Create a CRAAssessment for testing with a valid manufacturer configured."""
    team = sample_team_with_owner_member.team
    result = get_or_create_assessment(product.id, sample_user, team)
    assert result.ok
    return result.value


@pytest.mark.django_db
class TestGetOrCreateAssessment:
    def test_creates_assessment_with_ar_and_findings(self, sample_team_with_owner_member, sample_user, product):
        team = sample_team_with_owner_member.team
        result = get_or_create_assessment(product.id, sample_user, team)

        assert result.ok
        assessment = result.value
        assert assessment.product == product
        assert assessment.team == team
        assert assessment.oscal_assessment_result is not None
        assert assessment.status == CRAAssessment.WizardStatus.DRAFT
        assert assessment.current_step == 1
        assert assessment.completed_steps == []

        # Verify OSCAL AR + 21 findings
        ar = assessment.oscal_assessment_result
        assert ar.status == OSCALAssessmentResult.AssessmentStatus.IN_PROGRESS
        assert OSCALFinding.objects.filter(assessment_result=ar).count() == 21

    def test_returns_existing_assessment(self, sample_team_with_owner_member, sample_user, product):
        team = sample_team_with_owner_member.team
        result1 = get_or_create_assessment(product.id, sample_user, team)
        result2 = get_or_create_assessment(product.id, sample_user, team)

        assert result1.ok and result2.ok
        assert result1.value.id == result2.value.id
        assert CRAAssessment.objects.filter(product=product).count() == 1

    def test_auto_fills_from_contacts(self, sample_team_with_owner_member, sample_user, product_with_contacts):
        team = sample_team_with_owner_member.team
        result = get_or_create_assessment(product_with_contacts.id, sample_user, team)

        assert result.ok
        assessment = result.value
        assert assessment.csirt_contact_email == "security@acme.test"
        assert assessment.support_email == "info@acme.test"

    def test_auto_fills_support_period_from_product(self, sample_team_with_owner_member, sample_user):
        import datetime

        team = sample_team_with_owner_member.team
        product = Product.objects.create(
            name="Dated Product",
            team=team,
            end_of_support=datetime.date(2028, 12, 31),
        )

        result = get_or_create_assessment(product.id, sample_user, team)
        assert result.ok
        assert result.value.support_period_end == datetime.date(2028, 12, 31)

    def test_fails_for_nonexistent_product(self, sample_team_with_owner_member, sample_user):
        team = sample_team_with_owner_member.team
        result = get_or_create_assessment("nonexistent", sample_user, team)

        assert not result.ok
        assert result.status_code == 404

    def test_fails_for_wrong_team(self, sample_team_with_owner_member, sample_user, product):
        from sbomify.apps.teams.models import Team

        other_team = Team.objects.create(name="Other Team")
        result = get_or_create_assessment(product.id, sample_user, other_team)

        assert not result.ok
        assert result.status_code == 404


@pytest.mark.django_db
class TestGetStepContext:
    def test_step_1_returns_product_data(self, assessment):
        result = get_step_context(assessment, 1)

        assert result.ok
        data = result.value
        assert "product" in data
        assert data["product"]["name"] == "CRA Test Product"
        assert "intended_use" in data
        assert "product_category" in data
        assert "conformity_assessment_procedure" in data

    def test_step_2_returns_sbom_status(self, assessment):
        result = get_step_context(assessment, 2)

        assert result.ok
        data = result.value
        assert "components" in data
        assert "summary" in data

    def test_step_3_returns_grouped_findings(self, assessment):
        result = get_step_context(assessment, 3)

        assert result.ok
        data = result.value
        assert "control_groups" in data
        assert "summary" in data
        assert "vulnerability_handling" in data
        assert "article_14" in data

        # 5 groups
        assert len(data["control_groups"]) == 5

        # Summary counts
        assert data["summary"]["total"] == 21
        assert data["summary"]["unanswered"] == 21

    def test_step_4_returns_user_info_and_docs(self, assessment):
        result = get_step_context(assessment, 4)

        assert result.ok
        data = result.value
        assert "user_info" in data
        assert "documents" in data
        assert data["user_info"]["update_frequency"] == ""
        assert data["documents"] == {}

    def test_step_5_returns_summary(self, assessment):
        result = get_step_context(assessment, 5)

        assert result.ok
        data = result.value
        assert "product" in data
        assert "steps" in data
        assert "overall_ready" in data
        assert data["overall_ready"] is False

    def test_invalid_step_returns_error(self, assessment):
        result = get_step_context(assessment, 99)
        assert not result.ok
        assert result.status_code == 400


@pytest.mark.django_db
class TestSaveStepData:
    def test_step_1_saves_product_profile(self, assessment, sample_user):
        data = {
            "intended_use": "Home automation controller",
            "target_eu_markets": ["DE", "FR", "NL"],
            "product_category": "class_i",
            "is_open_source_steward": False,
            "harmonised_standard_applied": True,
            "support_period_end": str(
                datetime.date(datetime.date.today().year + 6, 6, 30)
            ),  # June 30, 6 years from now — always satisfies 5-year minimum (CRA Art 13(8))
        }
        result = save_step_data(assessment, 1, data, sample_user)

        assert result.ok
        a = result.value
        assert a.intended_use == "Home automation controller"
        assert a.target_eu_markets == ["DE", "FR", "NL"]
        assert a.product_category == "class_i"
        # Class I defaults to Module A (requires harmonised standard per CRA Art 32(2))
        assert a.conformity_assessment_procedure == CRAAssessment.ConformityProcedure.MODULE_A
        assert a.harmonised_standard_applied is True
        assert 1 in a.completed_steps
        assert a.status == CRAAssessment.WizardStatus.IN_PROGRESS

    def test_step_1_class_ii_sets_module_bc(self, assessment, sample_user):
        result = save_step_data(assessment, 1, {"product_category": "class_ii"}, sample_user)
        assert result.ok
        assert result.value.conformity_assessment_procedure == CRAAssessment.ConformityProcedure.MODULE_B_C

    def test_step_1_critical_defaults_to_module_bc(self, assessment, sample_user):
        """Critical products default to Module B+C (CRA Art 32(3)); EUCC not yet mandated."""
        result = save_step_data(assessment, 1, {"product_category": "critical"}, sample_user)
        assert result.ok
        assert result.value.conformity_assessment_procedure == CRAAssessment.ConformityProcedure.MODULE_B_C

    def test_step_1_class_i_without_harmonised_standard_rejected(self, assessment, sample_user):
        """Class I + Module A requires harmonised standard (CRA Art 32(2))."""
        result = save_step_data(assessment, 1, {"product_category": "class_i"}, sample_user)
        assert not result.ok
        assert result.status_code == 400
        assert "harmonised standard" in result.error.lower()

    def test_step_1_invalid_category_rejected(self, assessment, sample_user):
        result = save_step_data(assessment, 1, {"product_category": "invalid"}, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_1_rejects_placeholder_manufacturer(self, sample_team_with_owner_member, sample_user, product):
        """Server-side mirror of the ``canContinue`` gate. Even if a
        non-browser client skips the wizard's client-side check, the
        save endpoint refuses to mark step 1 complete when the team's
        manufacturer is a placeholder (Annex V item 2)."""
        team = sample_team_with_owner_member.team
        # Configure a placeholder manufacturer — "ABC" is in PLACEHOLDER_MANUFACTURER_VALUES
        profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
        ContactEntity.objects.create(
            profile=profile,
            name="ABC",
            email="abc@example.test",
            is_manufacturer=True,
        )
        result = get_or_create_assessment(product.id, sample_user, team)
        assert result.ok
        a = result.value

        # Use ``default`` category so the Class I + Module A harmonised
        # check (CRA Art 32(2)) introduced by the scope-screening work
        # doesn't fire first — this test targets the placeholder-manufacturer
        # guard (Annex V item 2) specifically.
        save = save_step_data(a, 1, {"product_category": "default"}, sample_user)

        assert not save.ok
        assert save.status_code == 400
        assert "Annex V" in (save.error or "")

    def test_step_1_absent_harmonised_flag_preserves_stored_value(self, assessment, sample_user):
        """Partial-PATCH semantic: absent key means "unchanged". A
        prior save that set ``harmonised_standard_applied=True`` must
        survive a subsequent Step 1 save that omits the key (e.g. the
        operator edits only ``intended_use`` on a second visit). The
        Art 32(2) gate is evaluated after the payload is applied, so
        the stored ``True`` keeps the Class I + Module A combination
        valid — which preserves presumption of conformity in the next
        DoC render."""
        support = str(datetime.date(datetime.date.today().year + 6, 6, 30))
        first = save_step_data(
            assessment,
            1,
            {
                "product_category": "class_i",
                "harmonised_standard_applied": True,
                "support_period_end": support,
            },
            sample_user,
        )
        assert first.ok
        assert first.value.harmonised_standard_applied is True

        # Second save omits the key — must succeed, flag must stay True.
        second = save_step_data(
            assessment,
            1,
            {"intended_use": "Updated description", "support_period_end": support},
            sample_user,
        )
        assert second.ok, second.error
        assessment.refresh_from_db()
        assert assessment.harmonised_standard_applied is True

    def test_step_1_explicit_false_harmonised_flag_fails_art_32_gate(self, assessment, sample_user):
        """The ``absent means unchanged`` semantic does not let
        operators bypass Art 32(2). Sending ``False`` explicitly still
        flips the flag and the gate blocks Class I + Module A."""
        support = str(datetime.date(datetime.date.today().year + 6, 6, 30))
        first = save_step_data(
            assessment,
            1,
            {
                "product_category": "class_i",
                "harmonised_standard_applied": True,
                "support_period_end": support,
            },
            sample_user,
        )
        assert first.ok

        second = save_step_data(
            assessment,
            1,
            {
                "product_category": "class_i",
                "harmonised_standard_applied": False,
                "support_period_end": support,
            },
            sample_user,
        )
        assert not second.ok
        assert second.status_code == 400
        assert "harmonised standard" in (second.error or "").lower()

    def test_step_1_support_period_justification_cleared_after_gate(self, assessment, sample_user):
        """CRA Art 13(8) audit-trail bypass regression (P0). A payload
        that submits ``support_period_short_justification=""`` with a
        <5-year support date must be rejected on the same save that
        tries to clear the justification — not pass the gate by
        reading the stored value and then silently overwrite it."""
        # First save: short support period + valid justification.
        short_date = str(datetime.date(datetime.date.today().year + 2, 1, 1))
        first = save_step_data(
            assessment,
            1,
            {
                "product_category": "default",
                "support_period_end": short_date,
                "support_period_short_justification": "product discontinued after 2 years",
            },
            sample_user,
        )
        assert first.ok
        # Second save: try to clear the justification — must fail.
        second = save_step_data(
            assessment,
            1,
            {
                "product_category": "default",
                "support_period_end": short_date,
                "support_period_short_justification": "",
            },
            sample_user,
        )
        assert not second.ok
        assert second.status_code == 400
        assert "5 years" in (second.error or "") or "justification" in (second.error or "").lower()

    def test_step_1_support_period_justification_whitespace_rejected(self, assessment, sample_user):
        """Whitespace-only justification is not a real audit record."""
        short_date = str(datetime.date(datetime.date.today().year + 2, 1, 1))
        result = save_step_data(
            assessment,
            1,
            {
                "product_category": "default",
                "support_period_end": short_date,
                "support_period_short_justification": "   \t\n   ",
            },
            sample_user,
        )
        assert not result.ok
        assert result.status_code == 400

    def test_step_1_support_period_justification_length_cap(self, assessment, sample_user):
        """4000-char cap mirrors the one on ``intended_use`` — a
        ``TextField`` with no DB-side size limit would otherwise let a
        client bloat the regulated-evidence row. Without the cap the
        stored value is returned to every subsequent Step 1 GET and
        dominates JSON serialisation time."""
        short_date = str(datetime.date(datetime.date.today().year + 2, 1, 1))
        result = save_step_data(
            assessment,
            1,
            {
                "product_category": "default",
                "support_period_end": short_date,
                "support_period_short_justification": "x" * 4_001,
            },
            sample_user,
        )
        assert not result.ok
        assert result.status_code == 400
        assert "4000-character cap" in (result.error or "")

    def test_step_1_rejects_non_eu_two_letter_code(self, assessment, sample_user):
        """EU-markets allowlist (P1). ``["XY"]`` passes the
        old length-only check but is not an EU member state; the DoC
        would list it verbatim. The allowlist must fail-closed."""
        support = str(datetime.date(datetime.date.today().year + 6, 6, 30))
        result = save_step_data(
            assessment,
            1,
            {
                "product_category": "default",
                "target_eu_markets": ["XY"],
                "support_period_end": support,
            },
            sample_user,
        )
        assert not result.ok
        assert result.status_code == 400
        assert "XY" in (result.error or "") or "country" in (result.error or "").lower()

    def test_step_1_rejects_non_eu_existing_two_letter(self, assessment, sample_user):
        """``US`` is a valid ISO 3166-1 alpha-2 code but not EU —
        regression seal for the narrower check."""
        support = str(datetime.date(datetime.date.today().year + 6, 6, 30))
        result = save_step_data(
            assessment,
            1,
            {"product_category": "default", "target_eu_markets": ["US"], "support_period_end": support},
            sample_user,
        )
        assert not result.ok
        assert result.status_code == 400

    def test_step_1_leap_day_support_period_clamp(self, assessment, sample_user):
        """Feb 29 release date → target year 5 years later (non-leap)
        must clamp to Feb 28, not crash on ``date.replace(year=…)``.
        Without this clamp, saving a support period of Feb 28 in the
        target year would be rejected as < 5 years despite being
        exactly the clamp boundary (CRA Art 13(8))."""
        # Seed a leap-day release date on the product.
        assessment.product.release_date = datetime.date(2024, 2, 29)
        assessment.product.save(update_fields=["release_date"])

        # 2029 is not a leap year — clamp to Feb 28. Feb 28 boundary
        # is exactly the minimum and must be accepted.
        boundary = str(datetime.date(2029, 2, 28))
        result = save_step_data(
            assessment,
            1,
            {"product_category": "default", "support_period_end": boundary},
            sample_user,
        )
        assert result.ok, result.error

        # Feb 27 2029 is one day below the clamp — should require justification.
        below = str(datetime.date(2029, 2, 27))
        result_below = save_step_data(
            assessment,
            1,
            {"product_category": "default", "support_period_end": below},
            sample_user,
        )
        assert not result_below.ok
        assert "5 years" in (result_below.error or "")

    def test_step_1_rejects_oversized_intended_use(self, assessment, sample_user):
        """Length cap on free-text ``intended_use`` (P1, row-bloat /
        DoS via JSON serialiser stall). 4 KB is generous."""
        support = str(datetime.date(datetime.date.today().year + 6, 6, 30))
        result = save_step_data(
            assessment,
            1,
            {
                "product_category": "default",
                "intended_use": "x" * 10_000,
                "support_period_end": support,
            },
            sample_user,
        )
        assert not result.ok
        assert result.status_code == 400
        assert "intended_use" in (result.error or "")

    def test_step_1_rejects_non_string_text_field(self, assessment, sample_user):
        """A non-string ``intended_use`` (``list`` / ``dict``) bypasses
        the ``isinstance(raw, str)`` branch of the length cap. Without
        an explicit type check the value would reach ``setattr`` and
        later blow up inside ``assessment.save()`` as a 500 or — worse —
        get coerced to a ``repr`` that defeats the row-bloat guard."""
        result = save_step_data(
            assessment,
            1,
            {"product_category": "default", "intended_use": ["bypass"] * 500},
            sample_user,
        )
        assert not result.ok
        assert result.status_code == 400
        assert "intended_use" in (result.error or "")

    def test_step_1_rejects_non_string_product_category(self, assessment, sample_user):
        """``product_category`` goes through a ``x not in set`` check. A
        ``list`` / ``dict`` payload would raise ``TypeError: unhashable
        type`` and become a 500. Require a string up front."""
        result = save_step_data(
            assessment,
            1,
            {"product_category": ["class_i"]},
            sample_user,
        )
        assert not result.ok
        assert result.status_code == 400
        assert "product_category" in (result.error or "")

    def test_step_2_marks_complete(self, assessment, sample_user):
        result = save_step_data(assessment, 2, {}, sample_user)
        assert result.ok
        assert 2 in result.value.completed_steps

    def test_step_2_accepts_tooling_limitation_waiver(self, assessment, sample_user):
        """Issue #907: operator can waive a tooling-limitation
        finding by supplying a justification. The waiver is stamped
        with timestamp + user id for audit."""
        data = {
            "waivers": {
                "bsi-tr03183:hash-value": {
                    "justification": "Accepted — syft does not emit SHA-512 for apt packages.",
                }
            }
        }
        result = save_step_data(assessment, 2, data, sample_user)

        assert result.ok
        waivers = result.value.bsi_waivers
        assert "bsi-tr03183:hash-value" in waivers
        assert waivers["bsi-tr03183:hash-value"]["justification"].startswith("Accepted")
        assert waivers["bsi-tr03183:hash-value"]["waived_at"]
        assert waivers["bsi-tr03183:hash-value"]["waived_by"] == sample_user.id

    def test_step_2_rejects_operator_action_waiver(self, assessment, sample_user):
        """Waiver is only valid for tooling_limitation findings.
        Attempting to waive an operator_action finding (e.g. missing
        SBOM creator) returns 400 — the gap would represent a genuine
        Annex I Part II(1) deficiency that must be fixed."""
        data = {
            "waivers": {
                "bsi-tr03183:sbom-creator": {"justification": "we don't feel like it"}
            }
        }
        result = save_step_data(assessment, 2, data, sample_user)
        assert not result.ok
        assert result.status_code == 400
        assert "cannot be waived" in (result.error or "")

    def test_step_2_rejects_unknown_finding_id(self, assessment, sample_user):
        """Typos in the waiver payload must not silently poison the
        ``bsi_waivers`` map. Only ids in the classifier whitelist
        are accepted."""
        data = {"waivers": {"bsi-tr03183:does-not-exist": {"justification": "x"}}}
        result = save_step_data(assessment, 2, data, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_2_rejects_empty_justification(self, assessment, sample_user):
        """Auditable waivers need a reason text. Empty / whitespace-
        only justification rejects so Annex VII documentation can
        explain why a tooling gap was accepted."""
        data = {"waivers": {"bsi-tr03183:hash-value": {"justification": "   "}}}
        result = save_step_data(assessment, 2, data, sample_user)
        assert not result.ok
        assert result.status_code == 400
        assert "justification" in (result.error or "").lower()

    def test_step_2_rejects_non_object_waivers_payload(self, assessment, sample_user):
        result = save_step_data(assessment, 2, {"waivers": "not-a-dict"}, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_3_updates_findings(self, assessment, sample_user):
        finding = OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result).first()

        data = {
            "findings": [
                {"finding_id": finding.id, "status": "satisfied", "notes": "Implemented"},
            ],
        }
        result = save_step_data(assessment, 3, data, sample_user)

        assert result.ok
        finding.refresh_from_db()
        assert finding.status == "satisfied"
        assert finding.notes == "Implemented"

    def test_step_3_updates_vuln_handling(self, assessment, sample_user):
        data = {
            "vulnerability_handling": {
                "vdp_url": "https://example.com/vdp",
                "acknowledgment_timeline_days": 5,
            },
        }
        result = save_step_data(assessment, 3, data, sample_user)

        assert result.ok
        a = result.value
        assert a.vdp_url == "https://example.com/vdp"
        assert a.acknowledgment_timeline_days == 5

    def test_step_3_updates_article_14(self, assessment, sample_user):
        data = {
            "article_14": {
                "csirt_country": "DE",
                "enisa_srp_registered": True,
            },
        }
        result = save_step_data(assessment, 3, data, sample_user)

        assert result.ok
        a = result.value
        assert a.csirt_country == "DE"
        assert a.enisa_srp_registered is True

    def test_step_3_invalid_finding_id(self, assessment, sample_user):
        data = {
            "findings": [
                {"finding_id": "nonexistent", "status": "satisfied"},
            ],
        }
        result = save_step_data(assessment, 3, data, sample_user)
        assert not result.ok
        assert result.status_code == 404

    def test_step_3_invalid_status(self, assessment, sample_user):
        finding = OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result).first()
        data = {
            "findings": [
                {"finding_id": finding.id, "status": "bogus"},
            ],
        }
        result = save_step_data(assessment, 3, data, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_3_vulnerability_handling_not_dict_rejected(self, assessment, sample_user):
        """Silent-drop regression: a non-dict ``vulnerability_handling``
        or wrong-type inner value previously skipped the write without
        any signal. An SDK/curl client would see a 200 while the DB
        retained the old value. Return 400 to match Step 1's strictness."""
        result = save_step_data(
            assessment, 3, {"vulnerability_handling": "not-a-dict"}, sample_user
        )
        assert not result.ok and result.status_code == 400

    def test_step_3_article_14_not_dict_rejected(self, assessment, sample_user):
        result = save_step_data(
            assessment, 3, {"article_14": ["not-a-dict"]}, sample_user
        )
        assert not result.ok and result.status_code == 400

    def test_step_3_vh_wrong_type_rejected(self, assessment, sample_user):
        """A non-string ``vdp_url`` (``list`` / ``dict`` / int) used to
        be silently dropped. Reject so the caller learns their payload
        shape is wrong."""
        result = save_step_data(
            assessment,
            3,
            {"vulnerability_handling": {"vdp_url": ["bypass"]}},
            sample_user,
        )
        assert not result.ok and result.status_code == 400

    def test_step_4_saves_user_info(self, assessment, sample_user):
        data = {
            "update_frequency": "quarterly",
            "update_method": "auto-with-opt-out",
            "support_email": "support@acme.test",
        }
        result = save_step_data(assessment, 4, data, sample_user)

        assert result.ok
        a = result.value
        assert a.update_frequency == "quarterly"
        assert a.update_method == "auto-with-opt-out"
        assert a.support_email == "support@acme.test"
        assert 4 in a.completed_steps

    def test_step_5_requires_previous_steps(self, assessment, sample_user):
        result = save_step_data(assessment, 5, {}, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_5_completes_assessment(self, assessment, sample_user):
        # Answer all findings so step 3 can be marked complete
        OSCALFinding.objects.filter(
            assessment_result=assessment.oscal_assessment_result,
        ).update(status="satisfied")

        # Complete steps 1-4 first
        save_step_data(assessment, 1, {"product_category": "default"}, sample_user)
        save_step_data(assessment, 2, {}, sample_user)
        save_step_data(assessment, 3, {}, sample_user)
        save_step_data(assessment, 4, {}, sample_user)
        assessment.refresh_from_db()

        result = save_step_data(assessment, 5, {}, sample_user)
        assert result.ok
        a = result.value
        assert a.status == CRAAssessment.WizardStatus.COMPLETE
        assert a.completed_at is not None
        assert a.oscal_assessment_result.status == "complete"

    def test_invalid_step_returns_error(self, assessment, sample_user):
        result = save_step_data(assessment, 99, {}, sample_user)
        assert not result.ok
        assert result.status_code == 400


@pytest.mark.django_db
class TestGetComplianceSummary:
    def test_returns_summary_shape(self, assessment):
        result = get_compliance_summary(assessment)

        assert result.ok
        data = result.value
        assert "product" in data
        assert "steps" in data
        assert "overall_ready" in data
        assert "export_available" in data
        assert data["overall_ready"] is False
        assert data["steps"][3]["controls"]["total"] == 21

    def test_overall_ready_when_all_steps_complete(self, assessment, sample_user):
        # Complete steps 1-4
        save_step_data(assessment, 1, {"product_category": "default"}, sample_user)
        save_step_data(assessment, 2, {}, sample_user)

        # Mark all findings as satisfied or not-applicable
        findings = OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result)
        for f in findings:
            f.status = "satisfied"
            f.save()

        save_step_data(assessment, 3, {}, sample_user)
        save_step_data(assessment, 4, {}, sample_user)
        assessment.refresh_from_db()

        result = get_compliance_summary(assessment)
        assert result.ok
        assert result.value["overall_ready"] is True


@pytest.mark.django_db
class TestGetAssessmentById:
    def test_returns_assessment(self, assessment):
        result = get_assessment_by_id(assessment.id)
        assert result.ok
        assert result.value is not None
        assert result.value.id == assessment.id
        # Verify select_related data is accessible without extra queries
        assert result.value.team is not None
        assert result.value.product is not None

    def test_nonexistent_returns_failure(self):
        result = get_assessment_by_id("nonexistent99")
        assert not result.ok
        assert result.status_code == 404


@pytest.mark.django_db
class TestGetAssessmentListForTeam:
    def test_returns_assessments_for_team(self, assessment, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        result = get_assessment_list_for_team(team.id)
        assert result.ok
        assert len(result.value) == 1
        item = result.value[0]
        assert item["id"] == assessment.id
        assert "product_name" in item
        assert "status" in item
        assert "status_value" in item
        assert "current_step" in item
        assert "completed_steps" in item
        assert "updated_at" in item

    def test_empty_for_other_team(self, assessment):
        from sbomify.apps.teams.models import Team

        other_team = Team.objects.create(name="Other Team")
        result = get_assessment_list_for_team(other_team.id)
        assert result.ok
        assert len(result.value) == 0

    def test_ordered_by_updated_at(self, sample_team_with_owner_member, sample_user):
        team = sample_team_with_owner_member.team
        p1 = Product.objects.create(name="Product A", team=team)
        p2 = Product.objects.create(name="Product B", team=team)
        r1 = get_or_create_assessment(p1.id, sample_user, team)
        r2 = get_or_create_assessment(p2.id, sample_user, team)
        assert r1.ok and r2.ok
        result = get_assessment_list_for_team(team.id)
        assert result.ok
        assert len(result.value) == 2
        # Most recently updated should be first
        assert result.value[0]["id"] == r2.value.id


@pytest.mark.django_db
class TestStepValidationEdgeCases:
    def test_step_1_invalid_eu_markets_rejected(self, assessment, sample_user):
        result = save_step_data(assessment, 1, {"target_eu_markets": ["DEU"]}, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_1_eu_markets_not_list_rejected(self, assessment, sample_user):
        result = save_step_data(assessment, 1, {"target_eu_markets": "DE"}, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_1_invalid_date_rejected(self, assessment, sample_user):
        result = save_step_data(assessment, 1, {"support_period_end": "not-a-date"}, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_1_null_date_clears_field(self, assessment, sample_user):
        import datetime

        assessment.support_period_end = datetime.date(2030, 1, 1)
        assessment.save()
        result = save_step_data(assessment, 1, {"support_period_end": None}, sample_user)
        assert result.ok
        result.value.refresh_from_db()
        assert result.value.support_period_end is None

    def test_step_3_findings_not_list_rejected(self, assessment, sample_user):
        result = save_step_data(assessment, 3, {"findings": "not-a-list"}, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_3_finding_not_dict_rejected(self, assessment, sample_user):
        result = save_step_data(assessment, 3, {"findings": ["not-a-dict"]}, sample_user)
        assert not result.ok
        assert result.status_code == 400

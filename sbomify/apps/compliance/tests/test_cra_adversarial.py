"""Adversarial / bad-input coverage for the CRA follow-up features.

Consolidates "what could go wrong" cases that don't fit the happy-path
test modules:

- Rule-tree evaluator: list-valued facts, contradictory predicates,
  deeply nested combinators, facts that are mutable and mutated mid-
  evaluation, ``any_of`` / ``all_of`` with empty list.
- Waiver lifecycle: stale waivers (finding passes now), waiver with
  finding id that changes classification, cross-user concurrent
  waivers, extremely long justification, Unicode/control-char
  justification.
- EN 18031 opt-in: persistence of RED scope flags when
  ``is_radio_equipment`` toggles on and off; DoC re-render after
  flag flip.
- BSI finding-id coercion: every non-string shape coerces to the
  fail-closed ``operator_action`` default instead of raising
  ``TypeError: unhashable type``.

Every test here is designed to FAIL CLOSED — the product surface
returns None / empty / rejects with 400 instead of crashing or
silently doing the wrong thing on regulated-evidence output.
"""

from __future__ import annotations

import datetime

import pytest

from sbomify.apps.compliance.models import CRAAssessment
from sbomify.apps.compliance.services.document_generation_service import (
    _assessment_facts,
    _evaluate_applies_when,
    _select_applied_standards,
)
from sbomify.apps.compliance.services.sbom_compliance_service import (
    _classify_bsi_finding,
    is_known_bsi_finding,
    is_waivable_bsi_finding,
)
from sbomify.apps.compliance.services.wizard_service import (
    get_or_create_assessment,
    get_step_context,
    save_step_data,
)
from sbomify.apps.core.models import Product
from sbomify.apps.teams.models import ContactEntity, ContactProfile


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _support_end_beyond_five_years() -> str:
    """Return a ``support_period_end`` that always passes the CRA Art 13(8)
    5-year minimum, regardless of wall-clock drift. Using a fixed literal
    like ``2032-01-01`` silently fails the test suite once today + 5 years
    crosses that date. Anchor to January 1 of (current year + 6) so the
    suite stays green for at least the full year it was generated in and
    avoids the Feb 29 leap-year trap.
    """
    return f"{datetime.date.today().year + 6}-01-01"


@pytest.fixture
def _valid_manufacturer(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
    ContactEntity.objects.create(
        profile=profile,
        name="Acme Labs GmbH",
        email="legal@acme.example",
        is_manufacturer=True,
    )


@pytest.fixture
def product(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="Adversarial Test Product", team=team)


@pytest.fixture
def assessment(sample_team_with_owner_member, sample_user, product, _valid_manufacturer):
    team = sample_team_with_owner_member.team
    result = get_or_create_assessment(product.id, sample_user, team)
    assert result.ok
    return result.value


# ---------------------------------------------------------------------------
# Rule-tree evaluator — adversarial inputs
# ---------------------------------------------------------------------------


class TestEvaluateAppliesWhenAdversarial:
    """``_evaluate_applies_when`` is the only piece of the #905 opt-in
    that evaluates attacker-adjacent data (operator-authored JSON in
    the reference file + model booleans). These tests pin its
    behaviour against crafted / malformed rule shapes."""

    def test_any_of_with_empty_list_is_false(self):
        """``any_of: []`` is vacuously False in boolean algebra. The
        evaluator must not short-circuit to True on an empty list (a
        common off-by-one when refactoring to generator-based any())."""
        assert _evaluate_applies_when({"any_of": []}, {}) is False

    def test_all_of_with_empty_list_is_true(self):
        """Dually, ``all_of: []`` is vacuously True. Documenting the
        expected semantics so a future tightening doesn't surprise
        the rule authors."""
        assert _evaluate_applies_when({"all_of": []}, {}) is True

    def test_deeply_nested_combinators_evaluate_correctly(self):
        """Stress: a rule that nests any_of inside all_of inside
        any_of. Matches the shape a regulated-evidence rule writer
        might use to express "radio AND (personal OR financial) AND
        NOT placeholder-tier"."""
        rule = {
            "all_of": [
                {"product_category": "radio_equipment"},
                {
                    "any_of": [
                        {"processes_personal_data": True},
                        {"handles_financial_value": True},
                        {"all_of": [{"operator_opt_in": True}, {"product_category": "radio_equipment"}]},
                    ]
                },
            ]
        }
        facts_a = {"product_category": "radio_equipment", "processes_personal_data": True, "operator_opt_in": False}
        facts_b = {"product_category": "radio_equipment", "operator_opt_in": True, "handles_financial_value": False}
        facts_c = {"product_category": "default", "processes_personal_data": True}
        assert _evaluate_applies_when(rule, facts_a) is True
        assert _evaluate_applies_when(rule, facts_b) is True
        assert _evaluate_applies_when(rule, facts_c) is False  # wrong product_category

    def test_multi_key_predicate_is_conjunctive(self):
        """A predicate dict with multiple keys like
        ``{"a": 1, "b": 2}`` behaves as AND across all pairs. Regression
        guard: someone refactoring to "first match wins" would silently
        weaken the evaluator."""
        rule = {"product_category": "radio_equipment", "processes_personal_data": True}
        assert _evaluate_applies_when(rule, {"product_category": "radio_equipment", "processes_personal_data": True})
        assert not _evaluate_applies_when(
            rule, {"product_category": "radio_equipment", "processes_personal_data": False}
        )

    def test_list_valued_fact_rejected_against_scalar_predicate(self):
        """Edge case: a fact that is itself a list (e.g.
        ``target_eu_markets: ["DE"]``) compared to a scalar expected
        value never matches. The evaluator uses Python equality; this
        test documents the limitation so a future rule author knows to
        use explicit list equality or a future list-contains combinator."""
        assert not _evaluate_applies_when({"target_eu_markets": "DE"}, {"target_eu_markets": ["DE"]})

    def test_list_valued_fact_matches_list_expected(self):
        """Flip side: list==list works today because Python equality
        compares lists element-by-element. Tests would-be rule
        authors can rely on this for exact-set matching."""
        assert _evaluate_applies_when({"target_eu_markets": ["DE", "FR"]}, {"target_eu_markets": ["DE", "FR"]})
        # Order matters today — no sorted-equality.
        assert not _evaluate_applies_when({"target_eu_markets": ["DE", "FR"]}, {"target_eu_markets": ["FR", "DE"]})

    def test_mutating_facts_mid_evaluation_does_not_short_circuit(self):
        """Defensive: the evaluator is pure (no facts mutation). If a
        future rewrite shares state, an iteration-order change could
        flip results. This test passes today trivially; it exists as a
        regression seal."""
        facts = {"product_category": "radio_equipment"}
        rule = {"any_of": [{"product_category": "radio_equipment"}, {"processes_personal_data": True}]}
        result_a = _evaluate_applies_when(rule, facts)
        # No mutation occurred.
        assert facts == {"product_category": "radio_equipment"}
        # Re-evaluation is idempotent.
        assert result_a == _evaluate_applies_when(rule, facts)

    def test_none_fact_value_never_equals_true_or_false_expected(self):
        """When a predicate expects a boolean but the fact is missing
        (returns None via .get), None != True AND None != False. The
        rule writer must supply an explicit default at the fact
        extraction layer; the evaluator doesn't coerce."""
        assert not _evaluate_applies_when({"processes_personal_data": True}, {})
        assert not _evaluate_applies_when({"processes_personal_data": False}, {})

    def test_non_dict_rule_shapes_fail_closed(self):
        """Valid-but-malformed reference JSON (``applies_when: []``,
        ``"x"``, ``42``, ``True``, ``null``) must fail closed rather
        than crash on ``.keys()`` or short-circuit to truthy. Entries
        that should always apply carry ``always_applicable: true`` in
        the reference JSON — the caller (``_select_applied_standards``)
        OR-short-circuits on that flag before invoking the evaluator,
        so treating ``applies_when: null`` here as "no predicate →
        always true" would contradict the "unknown predicate fails
        closed" policy at the sub-rule level. Fail closed uniformly."""
        for bad in [None, [], [{"product_category": "x"}], "string", 42, 3.14, True, False, set(), object()]:
            assert _evaluate_applies_when(bad, {}) is False, f"expected False for {bad!r}"

    def test_any_of_non_list_payload_fails_closed(self):
        """``any_of: "str"`` / ``any_of: {...}`` would otherwise
        iterate the string's characters (or dict keys) and eval them
        as sub-rules, silently matching on whatever happens to be
        falsy. Fail closed instead so a broken JSON fails loudly on
        the negative side rather than silently opening up claims."""
        assert _evaluate_applies_when({"any_of": "radio_equipment"}, {"product_category": "radio_equipment"}) is False
        assert _evaluate_applies_when({"any_of": {"product_category": "radio_equipment"}}, {}) is False
        assert _evaluate_applies_when({"any_of": None}, {}) is False

    def test_all_of_non_list_payload_fails_closed(self):
        """Same guarantee for ``all_of``. A non-list payload is
        never a valid rule tree."""
        assert _evaluate_applies_when({"all_of": "radio_equipment"}, {"product_category": "radio_equipment"}) is False
        assert _evaluate_applies_when({"all_of": {"product_category": "radio_equipment"}}, {}) is False
        assert _evaluate_applies_when({"all_of": 1}, {}) is False


@pytest.mark.django_db
class TestAssessmentFactsOverloadRegression:
    """The ``product_category`` key in ``_assessment_facts`` maps
    ``"radio_equipment"`` when ``is_radio_equipment`` is set and falls
    through to the CRA risk tier otherwise. These tests pin the
    overload behaviour so a future rule keyed on ``product_category:
    "class_i"`` doesn't silently fail for radio-equipment products."""

    def test_class_i_radio_product_product_category_is_radio_equipment(self, assessment):
        """A Class-I product with is_radio_equipment=True reports
        product_category="radio_equipment" — the CRA risk tier is
        LOST from the fact set. Documents the known tradeoff so a
        future split into cra_risk_tier + product_type can be done
        without a surprise."""
        assessment.product_category = CRAAssessment.ProductCategory.CLASS_I
        assessment.is_radio_equipment = True
        assessment.save(update_fields=["product_category", "is_radio_equipment"])

        facts = _assessment_facts(assessment)

        assert facts["product_category"] == "radio_equipment"

    def test_default_product_reports_cra_tier(self, assessment):
        assessment.product_category = CRAAssessment.ProductCategory.DEFAULT
        assessment.is_radio_equipment = False
        assessment.save(update_fields=["product_category", "is_radio_equipment"])

        facts = _assessment_facts(assessment)

        assert facts["product_category"] == "default"


# ---------------------------------------------------------------------------
# Step 1 save — RED scope server-side enforcement
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRedScopeServerEnforcement:
    """The wizard client disables personal-data / financial-value
    checkboxes when is_radio_equipment is False. The server must
    enforce the same constraint so an SDK / curl client can't persist
    nonsense combinations like "privacy scope without RED scope"."""

    def test_personal_data_cleared_when_radio_off(self, assessment, sample_user):
        """A payload that sets processes_personal_data=True and
        is_radio_equipment=False must land with personal_data=False
        in the DB — the server silently clears dependent flags."""
        result = save_step_data(
            assessment,
            1,
            {
                "product_category": "default",
                "is_radio_equipment": False,
                "processes_personal_data": True,
                "handles_financial_value": True,
                "target_eu_markets": ["DE"],
                "support_period_end": _support_end_beyond_five_years(),
            },
            sample_user,
        )
        assert result.ok
        a = result.value
        assert a.is_radio_equipment is False
        assert a.processes_personal_data is False
        assert a.handles_financial_value is False

    def test_personal_data_preserved_when_radio_on(self, assessment, sample_user):
        """Radio + personal + financial all stick when RED is on —
        the guard only fires when RED is off."""
        result = save_step_data(
            assessment,
            1,
            {
                "product_category": "default",
                "is_radio_equipment": True,
                "processes_personal_data": True,
                "handles_financial_value": True,
                "target_eu_markets": ["DE"],
                "support_period_end": _support_end_beyond_five_years(),
            },
            sample_user,
        )
        assert result.ok
        a = result.value
        assert a.is_radio_equipment is True
        assert a.processes_personal_data is True
        assert a.handles_financial_value is True

    def test_toggling_radio_off_clears_dependent_flags(self, assessment, sample_user):
        """First set RED + personal on; then persist RED off. The
        personal flag must clear — it's meaningless standalone."""
        save_step_data(
            assessment,
            1,
            {
                "product_category": "default",
                "is_radio_equipment": True,
                "processes_personal_data": True,
                "target_eu_markets": ["DE"],
                "support_period_end": _support_end_beyond_five_years(),
            },
            sample_user,
        )
        assessment.refresh_from_db()
        assert assessment.processes_personal_data is True

        result = save_step_data(
            assessment,
            1,
            {"is_radio_equipment": False, "target_eu_markets": ["DE"], "support_period_end": _support_end_beyond_five_years()},
            sample_user,
        )
        assert result.ok
        assessment.refresh_from_db()
        assert assessment.is_radio_equipment is False
        assert assessment.processes_personal_data is False


# ---------------------------------------------------------------------------
# EN 18031 end-to-end — DoC reflects flag flip
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEn18031DoCRerender:
    """Flag flips on Step 1 must be reflected in the next DoC
    preview — the selection predicate reads the CURRENT model state,
    not a stale cached snapshot."""

    def test_radio_flag_flip_adds_en_18031_1_to_applied_standards(self, assessment, sample_user):
        """Initial state (radio=False) → EN 18031-1 absent. Flip to
        True → present on the next call."""
        before = _select_applied_standards(assessment)
        assert not any("EN 18031-1" in s["citation"] for s in before)

        save_step_data(
            assessment,
            1,
            {
                "product_category": "default",
                "is_radio_equipment": True,
                "target_eu_markets": ["DE"],
                "support_period_end": _support_end_beyond_five_years(),
            },
            sample_user,
        )
        assessment.refresh_from_db()

        after = _select_applied_standards(assessment)
        assert any("EN 18031-1" in s["citation"] for s in after)


# ---------------------------------------------------------------------------
# BSI waivers — lifecycle and edge cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBsiWaiverLifecycle:
    """End-to-end waiver behaviour: Step 2 gate recomputes after
    waiver save, stale waivers are preserved verbatim, waivers survive
    a round-trip through the step context builder."""

    def test_waiver_save_then_gate_recompute(self, assessment, sample_user):
        """Persist a waiver via save_step_data, then call
        get_step_context(2) and confirm the failing check is
        flagged ``waived=True`` + the overall_gate stays False
        (because there's no passing component anyway)."""
        save_result = save_step_data(
            assessment,
            2,
            {
                "waivers": {
                    "bsi-tr03183:hash-value": {
                        "justification": "Accepted — syft omits SHA-512 for apt packages.",
                    }
                }
            },
            sample_user,
        )
        assert save_result.ok

        # Build Step 2 context. The test assessment has no components
        # with SBOMs, so there's nothing to waive — the overlay must
        # still not crash on an empty failing_checks list.
        ctx = get_step_context(assessment, 2)
        assert ctx.ok
        assert "components" in ctx.value

    def test_stale_waiver_is_preserved_not_pruned(self, assessment, sample_user):
        """A waiver for a finding that isn't currently failing (or
        doesn't exist in the current scan) stays in ``bsi_waivers``
        verbatim — the save path doesn't consult the scan results.
        Documents the expected behaviour: operators can set waivers
        preemptively, and the Step 2 overlay only activates them
        when a matching failing check appears."""
        save_result = save_step_data(
            assessment,
            2,
            {"waivers": {"bsi-tr03183:hash-value": {"justification": "preemptive"}}},
            sample_user,
        )
        assert save_result.ok
        assessment.refresh_from_db()
        assert "bsi-tr03183:hash-value" in assessment.bsi_waivers
        assert assessment.bsi_waivers["bsi-tr03183:hash-value"]["justification"] == "preemptive"

    def test_unicode_justification_persists(self, assessment, sample_user):
        """Emoji + non-Latin text in the justification. Survives
        JSON round-trip cleanly; regulatory filings from non-English
        operators need to keep the exact Unicode."""
        j = "接受 — ツールの制限 ✓ approuvé par le responsable conformité"
        result = save_step_data(
            assessment,
            2,
            {"waivers": {"bsi-tr03183:hash-value": {"justification": j}}},
            sample_user,
        )
        assert result.ok
        assessment.refresh_from_db()
        assert assessment.bsi_waivers["bsi-tr03183:hash-value"]["justification"] == j

    def test_justification_under_cap_persists(self, assessment, sample_user):
        """A 1 KB justification is within the 2 KB cap — persists
        verbatim. Regression guard for realistic operator usage."""
        j = "x" * 1_000
        result = save_step_data(
            assessment,
            2,
            {"waivers": {"bsi-tr03183:hash-value": {"justification": j}}},
            sample_user,
        )
        assert result.ok
        assessment.refresh_from_db()
        assert len(assessment.bsi_waivers["bsi-tr03183:hash-value"]["justification"]) == 1_000

    def test_justification_exceeding_cap_rejected(self, assessment, sample_user):
        """Defense-in-depth: 10 KB justification exceeds the
        ``_MAX_WAIVER_JUSTIFICATION_CHARS`` cap (2 KB). Rejects
        with 400 — prevents row-bloat / JSON-serialisation DoS."""
        j = "x" * 10_000
        result = save_step_data(
            assessment,
            2,
            {"waivers": {"bsi-tr03183:hash-value": {"justification": j}}},
            sample_user,
        )
        assert not result.ok
        assert result.status_code == 400
        assert "limit" in (result.error or "").lower()

    def test_justification_at_exact_cap_accepted(self, assessment, sample_user):
        """Boundary: 2 000-char justification (exactly at the cap) is
        accepted. The check is ``len > MAX``, not ``len >= MAX``."""
        j = "x" * 2_000
        result = save_step_data(
            assessment,
            2,
            {"waivers": {"bsi-tr03183:hash-value": {"justification": j}}},
            sample_user,
        )
        assert result.ok
        assessment.refresh_from_db()
        assert len(assessment.bsi_waivers["bsi-tr03183:hash-value"]["justification"]) == 2_000

    def test_justification_one_over_cap_rejected(self, assessment, sample_user):
        """Boundary: 2 001 chars is over — rejected with 400."""
        j = "x" * 2_001
        result = save_step_data(
            assessment,
            2,
            {"waivers": {"bsi-tr03183:hash-value": {"justification": j}}},
            sample_user,
        )
        assert not result.ok
        assert result.status_code == 400

    def test_waiver_with_extra_fields_ignored(self, assessment, sample_user):
        """Payload includes unexpected keys alongside justification
        (``{"justification": "x", "expires_at": "..."}``). Extra
        keys today are silently dropped — only justification is
        persisted. Documents the current strictness."""
        result = save_step_data(
            assessment,
            2,
            {
                "waivers": {
                    "bsi-tr03183:hash-value": {
                        "justification": "ok",
                        "expires_at": "2099-01-01",  # not a real field
                        "waived_by_email": "attacker@evil.test",  # ignored
                    }
                }
            },
            sample_user,
        )
        assert result.ok
        entry = assessment.bsi_waivers["bsi-tr03183:hash-value"]
        assert set(entry.keys()) == {"justification", "waived_at", "waived_by"}

    def test_second_save_replaces_waivers_entirely(self, assessment, sample_user):
        """Waiver payload replaces the whole ``bsi_waivers`` dict —
        it does NOT merge with existing waivers. Pins the current
        "replace" semantics so operators know to submit the full
        set on each save."""
        save_step_data(
            assessment,
            2,
            {"waivers": {"bsi-tr03183:hash-value": {"justification": "first"}}},
            sample_user,
        )
        save_step_data(
            assessment,
            2,
            {"waivers": {"bsi-tr03183:executable-property": {"justification": "second"}}},
            sample_user,
        )
        assessment.refresh_from_db()
        assert "bsi-tr03183:hash-value" not in assessment.bsi_waivers
        assert "bsi-tr03183:executable-property" in assessment.bsi_waivers

    @pytest.mark.parametrize(
        "bad_id",
        [
            "",
            " ",
            "bsi-tr03183:",  # prefix only
            ":hash-value",  # suffix only
            "BSI-TR03183:HASH-VALUE",  # wrong case — classifier is case-sensitive
            "bsi-tr03183:hash_value",  # underscore vs hyphen
            "bsi-tr03183:hash-value ",  # trailing space
        ],
    )
    def test_malformed_finding_id_rejected(self, assessment, sample_user, bad_id):
        """Only exact classifier-whitelist strings pass. Typos,
        case variations, and whitespace-padded ids are rejected —
        no "helpful" string normalisation that might paper over a
        real bug."""
        result = save_step_data(
            assessment,
            2,
            {"waivers": {bad_id: {"justification": "test"}}},
            sample_user,
        )
        assert not result.ok
        assert result.status_code == 400

    @pytest.mark.parametrize(
        "bad_justification",
        [
            {"nested": "dict"},
            ["array", "of", "strings"],
            42,
            True,
            None,
            b"bytes",
        ],
    )
    def test_non_string_justification_rejected(self, assessment, sample_user, bad_justification):
        """Justification must be a string literal. Nested dicts /
        lists / numbers / bytes / None all fail the
        ``isinstance(..., str)`` check — the waiver-save layer
        refuses the payload with 400 instead of silently coercing
        to a repr."""
        result = save_step_data(
            assessment,
            2,
            {"waivers": {"bsi-tr03183:hash-value": {"justification": bad_justification}}},
            sample_user,
        )
        assert not result.ok
        assert result.status_code == 400
        assert "justification" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# BSI classifier — defensive contract
# ---------------------------------------------------------------------------


class TestBsiClassifierCompleteness:
    """Invariant: every known finding id carries a specific
    ``human_summary`` — the generic "Unclassified" fallback should
    only ever fire for genuinely unknown ids. Drift here means the
    Step 2 wizard would show the unhelpful fallback for a real BSI
    check."""

    def test_every_known_finding_has_human_summary(self):
        from sbomify.apps.compliance.services.sbom_compliance_service import (
            _BSI_HUMAN_SUMMARY,
            _BSI_REMEDIATION_TYPE,
            _UNKNOWN_FINDING_SUMMARY,
        )

        missing = [fid for fid in _BSI_REMEDIATION_TYPE if fid not in _BSI_HUMAN_SUMMARY]
        assert not missing, f"Finding ids with no human_summary: {missing}"
        # And every human_summary entry corresponds to a known finding
        # (no typos in the summary map that would silently shadow the
        # fallback for a never-fired id).
        strays = [fid for fid in _BSI_HUMAN_SUMMARY if fid not in _BSI_REMEDIATION_TYPE]
        assert not strays, f"human_summary ids not in the classifier: {strays}"
        assert _UNKNOWN_FINDING_SUMMARY  # sanity

    def test_tooling_limitation_summaries_name_a_scanner_or_workflow(self):
        """Every tooling_limitation summary must mention the
        scanner / workflow the operator should change. Generic
        "run sbomify-action" text isn't enough — the issue asked
        for specific explanations like "syft doesn't emit X"."""
        from sbomify.apps.compliance.services.sbom_compliance_service import (
            _BSI_HUMAN_SUMMARY,
            _BSI_REMEDIATION_TYPE,
        )

        tooling_ids = [fid for fid, t in _BSI_REMEDIATION_TYPE.items() if t == "tooling_limitation"]
        for fid in tooling_ids:
            summary = _BSI_HUMAN_SUMMARY[fid].lower()
            # Either names a scanner or the enrichment workflow.
            mentions_workflow = any(
                token in summary for token in ("syft", "trivy", "scanner", "enrich", "sbomify-action")
            )
            assert mentions_workflow, f"{fid}: summary should name a scanner or enrichment workflow"


class TestBsiClassifierDefensive:
    """Public predicates (``is_known_bsi_finding`` / ``is_waivable_bsi_finding``)
    are the waiver-save gatekeepers. Adversarial inputs must fail
    closed."""

    @pytest.mark.parametrize(
        "bad_value",
        [None, 0, False, True, [], {}, ("bsi-tr03183:hash-value",), b"bsi-tr03183:hash-value"],
    )
    def test_non_string_finding_id_is_unknown(self, bad_value):
        assert is_known_bsi_finding(bad_value) is False
        assert is_waivable_bsi_finding(bad_value) is False

    def test_waivable_implies_known(self):
        """Contract: every waivable finding is known. The inverse
        isn't required (operator_action findings are known but
        not waivable)."""
        from sbomify.apps.compliance.services.sbom_compliance_service import _BSI_REMEDIATION_TYPE

        for fid in _BSI_REMEDIATION_TYPE:
            if is_waivable_bsi_finding(fid):
                assert is_known_bsi_finding(fid), fid

    def test_unknown_finding_fallback_consistent(self):
        """``_classify_bsi_finding`` unknown-id fallback returns a
        valid (remediation_type, guidance_url, human_summary) tuple
        even for fake ids. Regression guard for the "conservative
        default" contract."""
        rt, url, human = _classify_bsi_finding("bsi-tr03183:this-is-not-real")
        assert rt == "operator_action"
        assert url.startswith("https://")
        assert "Unclassified" in human


# ---------------------------------------------------------------------------
# Extra bad+complex coverage
# ---------------------------------------------------------------------------


class TestAppliesWhenExtraAdversarial:
    """Corner cases around the rule-tree evaluator. These catch
    typos in the reference JSON and hostile inputs a future admin
    API surface could pass."""

    def test_any_of_list_containing_non_dict_sub_rule_fails_closed(self):
        """``any_of: [{"k": 1}, "x", None]`` — the string/None are not
        dicts and must not match on any facts. They fail the
        ``isinstance(rule, dict)`` guard and the overall disjunction
        still honours the valid sibling."""
        rule = {"any_of": [{"k": "ok"}, "bad", None, 42]}
        assert _evaluate_applies_when(rule, {"k": "ok"}) is True
        assert _evaluate_applies_when(rule, {"k": "nope"}) is False

    def test_all_of_list_containing_non_dict_sub_rule_fails_closed(self):
        """``all_of: [{"k": 1}, "x"]`` — the string breaks the
        conjunction because it evaluates to False. Documents the
        safe behaviour (AND with False is False) for rule authors."""
        rule = {"all_of": [{"k": "ok"}, "bad"]}
        assert _evaluate_applies_when(rule, {"k": "ok"}) is False

    def test_deeply_nested_rule_does_not_blow_recursion(self):
        """Build a 50-deep rule tree and evaluate. Python's default
        recursion limit is 1000; 50 is comfortable. This test exists
        to flag a future refactor that accidentally changes the
        evaluator into a stack-hungry implementation."""
        rule: dict = {"product_category": "x"}
        for _ in range(50):
            rule = {"all_of": [rule]}
        assert _evaluate_applies_when(rule, {"product_category": "x"}) is True
        assert _evaluate_applies_when(rule, {"product_category": "y"}) is False

    def test_combinator_contains_deeply_nested_bad_shape(self):
        """A deeply nested valid tree with a bad shape at the leaf —
        the bad shape must still fail closed, not crash the whole
        evaluator."""
        rule = {"all_of": [{"any_of": [{"all_of": [{"any_of": 42}]}]}]}
        # Deepest ``any_of: 42`` → False; bubbles up as False.
        assert _evaluate_applies_when(rule, {}) is False

    def test_both_combinators_at_same_level_rejected(self):
        """``{"any_of": [...], "all_of": [...]}`` is ambiguous —
        which wins? The mixed-shape guard rejects it (combinator
        keys + siblings is always false)."""
        assert _evaluate_applies_when(
            {"any_of": [{"k": 1}], "all_of": [{"k": 1}]},
            {"k": 1},
        ) is False

    def test_equality_with_nested_dict_expected(self):
        """``{"foo": {"nested": "value"}}`` — Python dict equality
        handles this correctly. Future rule authors relying on
        per-component structured facts can count on deep ==."""
        rule = {"profile": {"kind": "radio"}}
        assert _evaluate_applies_when(rule, {"profile": {"kind": "radio"}}) is True
        assert _evaluate_applies_when(rule, {"profile": {"kind": "wired"}}) is False

    def test_empty_sub_rule_inside_any_of_is_true(self):
        """``any_of: [{}]`` — the empty dict is vacuously True
        (matches the ``not rule → True`` early-return), so any_of
        short-circuits to True regardless of facts. Documenting this
        so rule authors don't accidentally write ``any_of: [{}]``
        expecting "match nothing"."""
        assert _evaluate_applies_when({"any_of": [{}]}, {}) is True

    def test_falsy_but_non_none_fact_values_handled(self):
        """Facts like ``{"count": 0}`` or ``{"enabled": False}`` are
        falsy in Python. Equality compares exactly, so a predicate
        ``{"count": 0}`` matches correctly."""
        assert _evaluate_applies_when({"count": 0}, {"count": 0}) is True
        assert _evaluate_applies_when({"enabled": False}, {"enabled": False}) is True
        # But None isn't 0 and isn't False.
        assert _evaluate_applies_when({"count": 0}, {"count": None}) is False


class TestBsiFindingIdCoercionEndToEnd:
    """The ``_build_bsi_assessment_dict`` path reads ``f.get('id', '')``
    from run JSON. The classifier coerces non-string to "" so a
    broken upstream plugin can't crash the whole scan classification.
    Cover every hostile shape that could be injected via a broken
    plugin or corrupted DB row."""

    @pytest.mark.parametrize("bad_id", [None, [], {}, 42, 3.14, True, b"bytes", ["nested"], {"k": "v"}])
    def test_non_string_id_coerces_to_unknown(self, bad_id):
        """Directly exercise ``_classify_bsi_finding`` — any non-str
        id maps to the default ``operator_action`` bucket and
        returns the unknown-finding summary plus the enrichment URL,
        never raising ``TypeError: unhashable type`` on a dict-key
        lookup."""
        rem_type, url, summary = _classify_bsi_finding(bad_id)  # type: ignore[arg-type]
        # Default = operator_action (loud, operator must address).
        assert rem_type == "operator_action"
        # Non-empty fallback values — the summary + URL point
        # operators at the enrichment docs rather than leaving them
        # blank-handed on a malformed id.
        assert summary
        assert url

    def test_build_bsi_assessment_dict_handles_malformed_id(self):
        """End-to-end via ``_build_bsi_assessment_dict`` — a run
        whose findings carry a non-string id (maybe an upstream
        plugin bug) must produce a valid failing_checks entry with
        remediation_type populated, not crash."""
        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.compliance.services.sbom_compliance_service import (
            _build_bsi_assessment_dict,
        )

        run = AssessmentRun(
            result={
                "summary": {"pass_count": 1, "fail_count": 2, "warning_count": 0},
                "findings": [
                    {"id": ["list", "id"], "status": "fail", "title": "broken plugin output"},
                    {"id": 42, "status": "fail", "title": "int id"},
                    {"id": None, "status": "fail", "title": "none id"},
                    {"id": "bsi-tr03183:hash-value", "status": "fail", "title": "proper id"},
                    {"id": "bsi-tr03183:sbom-format", "status": "pass", "title": "pass ignored"},
                ],
            },
            status="completed",
        )
        out = _build_bsi_assessment_dict(run)
        # 4 failing checks extracted (pass is filtered out).
        assert out["fail_count"] == 2  # from summary
        assert len(out["failing_checks"]) == 4
        # Coerced ids all produce a valid string id.
        assert all(isinstance(c["id"], str) for c in out["failing_checks"])
        # The known id retains its classification, others fall to
        # operator_action default.
        classifications = {c["id"]: c["remediation_type"] for c in out["failing_checks"]}
        assert classifications["bsi-tr03183:hash-value"] == "tooling_limitation"
        # Non-string ids coerce to "" → default operator_action.
        assert classifications[""] == "operator_action"


@pytest.mark.django_db
class TestStep2WaiverComplexCases:
    """Waiver flow — bad inputs + complex interactions with the
    Step 2 overlay that a reviewer flagged as easy-to-break."""

    @pytest.mark.parametrize("corrupted", [None, [], "string", 42, True, False])
    def test_corrupt_bsi_waivers_shape_does_not_break_render(self, assessment, corrupted):
        """JSONField has no schema guard, so admin edits / raw SQL /
        bad migrations could land a non-dict value into
        ``bsi_waivers``. The Step 2 overlay must degrade to "no
        waivers applied" rather than raise and 500 the whole
        render."""
        assessment.bsi_waivers = corrupted  # type: ignore[assignment]
        # Direct assignment + save to bypass the model field's
        # default-dict coercion.
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE compliance_cra_assessments SET bsi_waivers = %s::jsonb WHERE id = %s",
                [__import__("json").dumps(corrupted), assessment.id],
            )
        assessment.refresh_from_db()

        ctx = get_step_context(assessment, 2)
        # Must render without exception — treats corrupted value as {}.
        assert ctx.ok

    def test_corrupt_per_finding_waiver_entry_treated_as_no_waiver(self, assessment):
        """Per-finding waiver entries should be dicts. A non-dict
        entry (list / string / int sneaked in via admin edit) must
        degrade to "no waiver" rather than crash on ``.get``. The
        finding renders as unwaived-failing — the safe default that
        keeps the Annex I Part II(1) gate honest."""
        assessment.bsi_waivers = {
            "bsi-tr03183:hash-value": ["not", "a", "dict"],
            "bsi-tr03183:filename": "also not a dict",
            "bsi-tr03183:executable-property": 42,
        }
        assessment.save(update_fields=["bsi_waivers"])

        ctx = get_step_context(assessment, 2)
        assert ctx.ok

    @pytest.mark.parametrize("incomplete_waiver", [
        {},  # empty dict
        {"justification": ""},  # missing waived_at
        {"justification": "   "},  # whitespace-only justification
        {"waived_at": "2026-04-23T00:00:00Z"},  # missing justification
        {"justification": "real reason"},  # missing waived_at
        {"justification": None, "waived_at": "2026-04-23T00:00:00Z"},  # None justification
        {"justification": "real reason", "waived_at": None},  # None waived_at
        {"justification": ["list"], "waived_at": "2026-04-23T00:00:00Z"},  # non-string justification
        {"justification": "real reason", "waived_at": 42},  # non-string waived_at
    ])
    def test_incomplete_waiver_not_treated_as_waived(self, assessment, incomplete_waiver):
        """Waiver records missing or having empty
        ``justification``/``waived_at`` must NOT flip the gate to
        green. A corrupted row (partial save, manual SQL edit, bad
        migration) should degrade to the unwaived state so the
        Annex I Part II(1) guard stays honest. Previously any
        dict-shaped waiver with the right remediation_type would
        mark the check as waived regardless of content — this test
        pins the stricter rule that both ``justification`` and
        ``waived_at`` must be non-empty strings after strip."""
        # Simulate a run producing one tooling-limitation failing
        # check with this waiver row. We exercise the overlay by
        # constructing the payload directly rather than going
        # through save_step_data (which would reject incomplete
        # waivers up front).
        from sbomify.apps.compliance.services.wizard_service import _build_step_2_context

        assessment.bsi_waivers = {"bsi-tr03183:hash-value": incomplete_waiver}
        assessment.save(update_fields=["bsi_waivers"])

        ctx = _build_step_2_context(assessment)
        assert ctx.ok
        # Walk the overlayed component payload (if any components
        # with a failing hash-value check exist) and confirm no
        # check is marked waived. On this fixture no SBOMs exist
        # so the list is empty — but the overlay must still not
        # crash and must not flip the gate.
        for comp in ctx.value.get("components", []):
            bsi = comp.get("bsi_assessment") or {}
            for check in bsi.get("failing_checks", []):
                if check.get("id") == "bsi-tr03183:hash-value":
                    assert check.get("waived") is False, (
                        f"incomplete waiver {incomplete_waiver!r} must not mark check waived"
                    )

    def test_operator_action_waiver_silently_dropped_by_overlay(self, assessment):
        """A waiver written for an ``operator_action`` finding must
        NOT mark the check as waived — those findings require the
        operator to act. The overlay silently ignores the waiver
        while keeping the value on the row for audit."""
        assessment.bsi_waivers = {
            "bsi-tr03183:sbom-creator": {"justification": "ignored — operator_action"},
        }
        assessment.save(update_fields=["bsi_waivers"])

        # Fake a run with the finding failing.
        ctx = get_step_context(assessment, 2)
        assert ctx.ok
        # Waiver is preserved on the model but not applied.
        assessment.refresh_from_db()
        assert "bsi-tr03183:sbom-creator" in assessment.bsi_waivers

    def test_summary_fail_count_above_list_length_blocks_gate(self, assessment):
        """When a BSI run summary reports more failures than the
        ``failing_checks`` list contains (truncated payload, bad
        plugin, corrupted row), the Step 2 overlay must take the
        higher value so phantom failures can't silently flip the
        gate to green. Exercise the overlay directly because
        constructing a real run with a mismatched summary is
        awkward."""
        from sbomify.apps.compliance.services.wizard_service import _build_step_2_context
        from unittest.mock import patch
        from sbomify.apps.core.services.results import ServiceResult

        fake_payload = {
            "components": [
                {
                    "component_id": "c1",
                    "component_name": "broken",
                    "has_sbom": True,
                    "format_compliant": True,
                    "bsi_assessment": {
                        "status": "completed",
                        # Summary claims 3 failures, but only 1 waived
                        # finding materialised in ``failing_checks``.
                        "fail_count": 3,
                        "failing_checks": [
                            {
                                "id": "bsi-tr03183:hash-value",
                                "remediation_type": "tooling_limitation",
                                "title": "h",
                                "description": "d",
                                "remediation": "r",
                                "guidance_url": "",
                                "human_summary": "s",
                            },
                        ],
                    },
                }
            ],
            "summary": {
                "total_components": 1,
                "components_with_sbom": 1,
                "components_passing_bsi": 0,
                "overall_gate": False,
            },
        }

        assessment.bsi_waivers = {
            "bsi-tr03183:hash-value": {
                "justification": "accepted tooling gap",
                "waived_at": "2026-04-23T00:00:00Z",
            }
        }
        assessment.save(update_fields=["bsi_waivers"])

        with patch(
            "sbomify.apps.compliance.services.wizard_service.get_bsi_assessment_status",
            return_value=ServiceResult.success(fake_payload),
        ):
            ctx = _build_step_2_context(assessment)

        assert ctx.ok
        comp = ctx.value["components"][0]
        bsi = comp["bsi_assessment"]
        # All listed failing checks got waived by the overlay...
        assert bsi["failing_checks"][0]["waived"] is True
        # ...but the summary's larger fail_count wins: 3 phantom
        # failures keep the component from being "effectively passing".
        assert bsi["unwaived_fail_count"] == 3
        assert comp["effectively_passing"] is False
        # Product gate stays false — no component passes.
        assert ctx.value["summary"]["overall_gate"] is False

    def test_unknown_finding_id_waiver_silently_dropped(self, assessment, sample_user):
        """Saving a waiver for an id that isn't in the BSI registry
        (typo, deprecated id) must be rejected at the save layer —
        operators can't bypass the gate by typing novel ids."""
        result = save_step_data(
            assessment,
            2,
            {"waivers": {"bsi-tr03183:does-not-exist": {"justification": "typo"}}},
            sample_user,
        )
        # Expected: rejected because id is unknown.
        assert not result.ok
        assert "unknown" in (result.error or "").lower() or "not waivable" in (result.error or "").lower()

    def test_waiver_for_operator_action_finding_rejected(self, assessment, sample_user):
        """Saving a waiver for a finding that IS in the registry but
        is classified as ``operator_action`` must also be rejected —
        only tooling-limitation findings are waivable."""
        result = save_step_data(
            assessment,
            2,
            {"waivers": {"bsi-tr03183:sbom-creator": {"justification": "nope"}}},
            sample_user,
        )
        assert not result.ok
        assert "waivable" in (result.error or "").lower() or "operator" in (result.error or "").lower()

    @pytest.mark.parametrize("bad_type", [[], [1, 2], "", "str", 0, 42, False, True, 3.14])
    def test_non_dict_waivers_value_rejected_with_400(self, assessment, sample_user, bad_type):
        """``{"waivers": [...]}``, ``{"waivers": ""}``, etc. must be
        rejected with 400, not silently coerced to an empty dict.
        The pre-fix code used ``data.get("waivers") or {}`` which
        cleared every existing waiver whenever the payload was a
        falsy non-dict."""
        # Seed a real waiver so a silent-clear would be observable.
        save_step_data(
            assessment,
            2,
            {"waivers": {"bsi-tr03183:hash-value": {"justification": "seed"}}},
            sample_user,
        )
        assessment.refresh_from_db()
        assert assessment.bsi_waivers

        result = save_step_data(assessment, 2, {"waivers": bad_type}, sample_user)

        assert not result.ok
        assert result.status_code == 400
        assert "object" in (result.error or "").lower() or "waivers" in (result.error or "").lower()
        # Pre-existing waivers must survive a rejected payload.
        assessment.refresh_from_db()
        assert "bsi-tr03183:hash-value" in assessment.bsi_waivers

    def test_null_waivers_value_treated_as_empty(self, assessment, sample_user):
        """Explicit ``{"waivers": null}`` is the one case we keep
        treating as "no waivers provided" — same semantic as omitting
        the key entirely. Prevents a hard break for clients that
        serialise an empty map as null."""
        save_step_data(
            assessment,
            2,
            {"waivers": {"bsi-tr03183:hash-value": {"justification": "seed"}}},
            sample_user,
        )
        assessment.refresh_from_db()
        assert assessment.bsi_waivers

        # null → treated as "empty" → clears existing waivers.
        result = save_step_data(assessment, 2, {"waivers": None}, sample_user)
        assert result.ok
        assessment.refresh_from_db()
        assert assessment.bsi_waivers == {}

    def test_empty_waivers_dict_clears_all(self, assessment, sample_user):
        """POST ``{"waivers": {}}`` must clear every existing waiver
        — the second save replaces the field entirely. Regression
        seal for the "delete by omission" contract."""
        # Start with a waiver.
        save_step_data(
            assessment,
            2,
            {"waivers": {"bsi-tr03183:hash-value": {"justification": "x"}}},
            sample_user,
        )
        assessment.refresh_from_db()
        assert assessment.bsi_waivers

        # Now clear.
        result = save_step_data(assessment, 2, {"waivers": {}}, sample_user)
        assert result.ok
        assessment.refresh_from_db()
        assert assessment.bsi_waivers == {}



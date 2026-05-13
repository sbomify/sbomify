import { registerAlpineComponent } from '../../core/js/alpine-components';
import { EU_COUNTRIES, EU_COUNTRY_NAMES } from './eu-countries';
import { getAssessmentId, saveStepAndNavigate } from './cra-shared';

interface ProductInfo {
  id: string;
  name: string;
  description: string;
  release_date: string | null;
  end_of_support: string | null;
  end_of_life: string | null;
}

interface ManufacturerInfo {
  name: string;
  address: string;
  email: string;
  website_urls: string[];
}

// Procedure metadata: label + optional note for UI display
// CRA Art 32(1-5) defines which procedures are allowed per product category
const PROCEDURE_INFO: Record<string, { label: string; note: string }> = {
  module_a: {
    label: 'Module A — Internal production control (self-assessment)',
    note: 'CRA Art 32(1). For Class I: only if harmonised standard applied (Art 32(2)).',
  },
  module_b_c: {
    label: 'Module B+C — EU-type examination (notified body)',
    note: 'CRA Art 32(3). Design examination + production quality assurance.',
  },
  module_h: {
    label: 'Module H — Full quality assurance (notified body)',
    note: 'CRA Art 32(4). Comprehensive QA system assessed by notified body.',
  },
  eucc: {
    label: 'EUCC — EU Cybersecurity Certification',
    note: 'Only mandatory if established under CRA Art 8(1) — not yet in effect.',
  },
};

function craStep1() {
  return {
    assessmentId: '',
    product: {} as ProductInfo,
    manufacturer: null as ManufacturerInfo | null,
    // Wizard-side mirror of the backend placeholder check so the UI can
    // warn the operator BEFORE they reach Step 5 and discover the
    // DoC rendered "[Manufacturer Name — not configured]". Backend
    // source of truth: services._manufacturer_policy.is_placeholder_manufacturer.
    manufacturerIsPlaceholder: false as boolean,
    category: 'default',
    isOpenSourceSteward: false,
    harmonisedStandardApplied: false,
    // EN 18031 applicability flags (issue #905). Orthogonal to the
    // CRA risk-tier ``category`` — a Class I product may or may not
    // be radio equipment. Ticking ``isRadioEquipment`` triggers
    // EN 18031-1 in the DoC; pairing it with the scope flags below
    // pulls in EN 18031-2 / -3.
    isRadioEquipment: false,
    processesPersonalData: false,
    handlesFinancialValue: false,
    euMarkets: [] as string[],
    supportPeriodEnd: '',
    supportPeriodMinEnd: '',
    supportPeriodShortJustification: '',
    intendedUse: '',
    conformityAssessmentProcedure: '',
    conformityProcedureOptions: {} as Record<string, string[]>,
    isSaving: false,
    euCountries: EU_COUNTRIES,
    euCountryNames: EU_COUNTRY_NAMES,

    init() {
      const data = window.parseJsonScript('step-data');
      if (data) {
        const d = data as Record<string, unknown>;
        this.product = (d.product as ProductInfo) || {};
        this.manufacturer = (d.manufacturer as ManufacturerInfo) || null;
        this.manufacturerIsPlaceholder = Boolean(d.manufacturer_is_placeholder);
        this.category = (d.product_category as string) || 'default';
        this.isOpenSourceSteward = !!(d.is_open_source_steward);
        this.harmonisedStandardApplied = !!(d.harmonised_standard_applied);
        this.isRadioEquipment = !!(d.is_radio_equipment);
        this.processesPersonalData = !!(d.processes_personal_data);
        this.handlesFinancialValue = !!(d.handles_financial_value);
        this.euMarkets = (d.target_eu_markets as string[]) || [];
        this.supportPeriodEnd = (d.support_period_end as string) || '';
        // Server-computed 5-year minimum — mirrors the backend Art 13(8)
        // gate so the UI and the 400 response never disagree across
        // time zones / near-midnight client clocks.
        this.supportPeriodMinEnd = (d.support_period_min_end as string) || '';
        this.supportPeriodShortJustification = (d.support_period_short_justification as string) || '';
        this.intendedUse = (d.intended_use as string) || '';
        this.conformityAssessmentProcedure =
          (d.conformity_assessment_procedure as string) || '';
        this.conformityProcedureOptions =
          (d.conformity_procedure_options as Record<string, string[]>) || {};
      }
      this.assessmentId = getAssessmentId();

      // Normalize loaded procedure. Three cases:
      //   1. Empty — new assessments or step-data without a saved
      //      procedure. Default to the first allowed option for the
      //      category so the UI never renders an empty radio group
      //      and ``canContinue`` doesn't let the user submit an empty
      //      ``conformity_assessment_procedure`` (the backend would
      //      400 that and the user would see no hint why).
      //   2. Saved but not in the allowed set — e.g. a legacy
      //      ``eucc`` value on a Critical assessment made before the
      //      category→procedure mapping changed. Snap to the first
      //      allowed option to match how the backend default path
      //      behaves.
      //   3. Saved and allowed — leave it alone.
      const initAllowed = this.conformityProcedureOptions[this.category] || ['module_a'];
      if (!this.conformityAssessmentProcedure || !initAllowed.includes(this.conformityAssessmentProcedure)) {
        this.conformityAssessmentProcedure = initAllowed[0];
      }

      // Narrow ``$watch`` typing once — registerAlpineComponent doesn't
      // propagate Alpine's magics so we cast the ``this`` context to
      // an interface exposing just the watcher signature.
      const watchable = this as unknown as {
        $watch: (prop: string, cb: (val: unknown) => void) => void;
      };

      // When category changes, auto-select the first allowed procedure if current is invalid
      watchable.$watch('category', (newCatValue: unknown) => {
        const newCat = String(newCatValue);
        const allowed = this.conformityProcedureOptions[newCat] || ['module_a'];
        if (!allowed.includes(this.conformityAssessmentProcedure)) {
          this.conformityAssessmentProcedure = allowed[0];
        }
        // Reset harmonised standard when not Class I
        if (newCat !== 'class_i') {
          this.harmonisedStandardApplied = false;
        }
      });

      // EN 18031-2/-3 only apply to radio equipment (issue #905).
      // When the operator un-ticks ``isRadioEquipment`` the two
      // dependent scope flags must follow — the template disables
      // them but the bound values survive, which persists an
      // inconsistent state and renders as "disabled-but-checked"
      // on the next page load. The backend's _save_step_1 already
      // clears these defensively; this mirror prevents the stale
      // tick from reaching the save call in the first place.
      watchable.$watch('isRadioEquipment', (val: unknown) => {
        if (!val) {
          this.processesPersonalData = false;
          this.handlesFinancialValue = false;
        }
      });
    },

    get canContinue(): boolean {
      // CRA Annex V item 2 requires the manufacturer's legal name on
      // the generated DoC. When the team profile still carries a
      // placeholder (or none) we refuse to advance past Step 1 — this
      // is the wizard-side prevention that pairs with the render-time
      // safety net in document_generation_service._build_common_context.
      // Issue #908.
      if (this.manufacturerIsPlaceholder) return false;
      if (!this.category || this.euMarkets.length === 0 || !this.supportPeriodEnd) return false;
      // Refuse to submit without a procedure. The ``init`` and category
      // watcher default to the first allowed option, so an empty value
      // only appears if the options map is missing for the chosen
      // category — the backend would 400 and the user would have no
      // clear signal why.
      if (!this.conformityAssessmentProcedure) return false;
      // If support period < 5 years, justification is required (CRA Art 13(8))
      if (this.supportPeriodShort && !this.supportPeriodShortJustification.trim()) return false;
      // Class I + Module A requires harmonised standard (CRA Art 32(2))
      if (
        this.category === 'class_i' &&
        this.conformityAssessmentProcedure === 'module_a' &&
        !this.harmonisedStandardApplied
      ) return false;
      return true;
    },

    /** Whether the selected support period is less than 5 years from reference date.
     *
     * Compares the operator-entered ``YYYY-MM-DD`` string against the
     * server-computed ``supportPeriodMinEnd`` directly — both are
     * canonicalised on the backend, so lexical comparison is equivalent
     * to chronological comparison and we avoid every tz/DST edge case
     * that plagued the previous client-side ``new Date()`` path.
     */
    get supportPeriodShort(): boolean {
      if (!this.supportPeriodEnd || !this.supportPeriodMinEnd) return false;
      if (!/^\d{4}-\d{2}-\d{2}$/.test(this.supportPeriodEnd)) return false;
      return this.supportPeriodEnd < this.supportPeriodMinEnd;
    },

    /** Available conformity procedures for the current category (CRA Art 32). */
    get availableProcedures(): { value: string; label: string; note: string }[] {
      const allowed = this.conformityProcedureOptions[this.category] || ['module_a'];
      return allowed.map((proc: string) => ({
        value: proc,
        label: PROCEDURE_INFO[proc]?.label || proc,
        note: PROCEDURE_INFO[proc]?.note || '',
      }));
    },

    get allMarketsSelected(): boolean {
      return this.euMarkets.length === EU_COUNTRIES.length;
    },

    toggleAllMarkets(): void {
      if (this.allMarketsSelected) {
        this.euMarkets = [];
      } else {
        this.euMarkets = [...EU_COUNTRIES];
      }
    },

    toggleMarket(code: string): void {
      const idx = this.euMarkets.indexOf(code);
      if (idx >= 0) {
        this.euMarkets.splice(idx, 1);
      } else {
        this.euMarkets.push(code);
      }
    },

    isMarketSelected(code: string): boolean {
      return this.euMarkets.includes(code);
    },

    async save(): Promise<void> {
      if (!this.canContinue || this.isSaving) return;
      await saveStepAndNavigate(this.assessmentId, 1, {
        product_category: this.category,
        is_open_source_steward: this.isOpenSourceSteward,
        harmonised_standard_applied: this.harmonisedStandardApplied,
        conformity_assessment_procedure: this.conformityAssessmentProcedure,
        is_radio_equipment: this.isRadioEquipment,
        processes_personal_data: this.processesPersonalData,
        handles_financial_value: this.handlesFinancialValue,
        target_eu_markets: this.euMarkets,
        support_period_end: this.supportPeriodEnd,
        support_period_short_justification: this.supportPeriodShortJustification,
        intended_use: this.intendedUse,
      }, (v) => { this.isSaving = v; });
    },
  };
}

export function registerCraStep1(): void {
  registerAlpineComponent('craStep1', craStep1);
}

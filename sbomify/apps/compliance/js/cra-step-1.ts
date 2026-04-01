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
    category: 'default',
    isOpenSourceSteward: false,
    harmonisedStandardApplied: false,
    euMarkets: [] as string[],
    supportPeriodEnd: '',
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
        this.category = (d.product_category as string) || 'default';
        this.isOpenSourceSteward = !!(d.is_open_source_steward);
        this.harmonisedStandardApplied = !!(d.harmonised_standard_applied);
        this.euMarkets = (d.target_eu_markets as string[]) || [];
        this.supportPeriodEnd = (d.support_period_end as string) || '';
        this.supportPeriodShortJustification = (d.support_period_short_justification as string) || '';
        this.intendedUse = (d.intended_use as string) || '';
        this.conformityAssessmentProcedure =
          (d.conformity_assessment_procedure as string) || '';
        this.conformityProcedureOptions =
          (d.conformity_procedure_options as Record<string, string[]>) || {};
      }
      this.assessmentId = getAssessmentId();

      // When category changes, auto-select the first allowed procedure if current is invalid
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (this as any).$watch('category', (newCat: string) => {
        const allowed = this.conformityProcedureOptions[newCat] || ['module_a'];
        if (!allowed.includes(this.conformityAssessmentProcedure)) {
          this.conformityAssessmentProcedure = allowed[0];
        }
        // Reset harmonised standard when not Class I
        if (newCat !== 'class_i') {
          this.harmonisedStandardApplied = false;
        }
      });
    },

    get canContinue(): boolean {
      if (!this.category || this.euMarkets.length === 0 || !this.supportPeriodEnd) return false;
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

    /** Whether the selected support period is less than 5 years from reference date. */
    get supportPeriodShort(): boolean {
      if (!this.supportPeriodEnd) return false;
      const refDate = this.product.release_date
        ? new Date(this.product.release_date)
        : new Date();
      const minEnd = new Date(refDate);
      minEnd.setFullYear(minEnd.getFullYear() + 5);
      return new Date(this.supportPeriodEnd) < minEnd;
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

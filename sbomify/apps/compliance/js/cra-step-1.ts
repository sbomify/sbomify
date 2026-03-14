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

const CONFORMITY_MAP: Record<string, string> = {
  default: 'Module A (Internal production control)',
  class_i: 'Module A or EUCC scheme',
  class_ii: 'Module B+C or Module H or EUCC scheme',
  critical: 'EUCC scheme (mandatory third-party)',
};

function craStep1() {
  return {
    assessmentId: '',
    product: {} as ProductInfo,
    manufacturer: null as ManufacturerInfo | null,
    category: 'default',
    isOpenSourceSteward: false,
    euMarkets: [] as string[],
    supportPeriodEnd: '',
    intendedUse: '',
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
        this.euMarkets = (d.target_eu_markets as string[]) || [];
        this.supportPeriodEnd = (d.support_period_end as string) || '';
        this.intendedUse = (d.intended_use as string) || '';
      }
      this.assessmentId = getAssessmentId();
    },

    get canContinue(): boolean {
      return !!this.category && this.euMarkets.length > 0 && !!this.supportPeriodEnd;
    },

    get conformityProcedure(): string {
      return CONFORMITY_MAP[this.category] || CONFORMITY_MAP.default;
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
        target_eu_markets: this.euMarkets,
        support_period_end: this.supportPeriodEnd,
        intended_use: this.intendedUse,
      }, (v) => { this.isSaving = v; });
    },
  };
}

export function registerCraStep1(): void {
  registerAlpineComponent('craStep1', craStep1);
}

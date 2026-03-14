import { registerAlpineComponent } from '../../core/js/alpine-components';
import { getAssessmentId, saveStepAndNavigate } from './cra-shared';

const PRODUCT_TYPE_TEMPLATES: Record<string, Record<string, string>> = {
  web_app: { update_frequency: 'regular', update_method: 'Automatic server-side', support_hours: 'Mon-Fri 9-17 CET' },
  mobile: { update_frequency: 'regular', update_method: 'App store update', support_hours: 'Mon-Fri 9-17 CET' },
  iot: { update_frequency: 'as-needed', update_method: 'OTA firmware update', support_hours: '24/7 via portal' },
  desktop: { update_frequency: 'regular', update_method: 'Auto-updater', support_hours: 'Mon-Fri 9-17 CET' },
  library: { update_frequency: 'as-needed', update_method: 'Package manager', support_hours: 'Community support' },
  network: { update_frequency: 'as-needed', update_method: 'Firmware update', support_hours: '24/7' },
  embedded: { update_frequency: 'as-needed', update_method: 'Firmware flash', support_hours: 'Business hours' },
  cloud: { update_frequency: 'regular', update_method: 'Continuous deployment', support_hours: '24/7' },
  os: { update_frequency: 'regular', update_method: 'System updater', support_hours: 'Mon-Fri 9-17' },
  api: { update_frequency: 'regular', update_method: 'Automatic server-side', support_hours: '24/7 via status page' },
};

function craStep4() {
  return {
    assessmentId: '',
    productType: '',
    updateFrequency: '',
    updateMethod: '',
    updateChannelUrl: '',
    supportEmail: '',
    supportUrl: '',
    supportPhone: '',
    supportHours: '',
    dataDeletionInstructions: '',
    isSaving: false,

    init() {
      const data = window.parseJsonScript('step-data') as Record<string, unknown> | null;
      if (data) {
        const ui = (data.user_info as Record<string, string>) || {};
        this.updateFrequency = ui.update_frequency || '';
        this.updateMethod = ui.update_method || '';
        this.updateChannelUrl = ui.update_channel_url || '';
        this.supportEmail = ui.support_email || '';
        this.supportUrl = ui.support_url || '';
        this.supportPhone = ui.support_phone || '';
        this.supportHours = ui.support_hours || '';
        this.dataDeletionInstructions = ui.data_deletion_instructions || '';
      }
      this.assessmentId = getAssessmentId();
    },

    applyTemplate(type: string): void {
      this.productType = type;
      const tmpl = PRODUCT_TYPE_TEMPLATES[type];
      if (tmpl) {
        if (!this.updateFrequency) this.updateFrequency = tmpl.update_frequency || '';
        if (!this.updateMethod) this.updateMethod = tmpl.update_method || '';
        if (!this.supportHours) this.supportHours = tmpl.support_hours || '';
      }
    },

    get canContinue(): boolean {
      return !!(this.updateMethod && (this.supportEmail || this.supportUrl) && this.dataDeletionInstructions);
    },

    async save(): Promise<void> {
      if (!this.canContinue || this.isSaving) return;
      await saveStepAndNavigate(this.assessmentId, 4, {
        update_frequency: this.updateFrequency,
        update_method: this.updateMethod,
        update_channel_url: this.updateChannelUrl,
        support_email: this.supportEmail,
        support_url: this.supportUrl,
        support_phone: this.supportPhone,
        support_hours: this.supportHours,
        data_deletion_instructions: this.dataDeletionInstructions,
      }, (v) => { this.isSaving = v; });
    },
  };
}

export function registerCraStep4(): void {
  registerAlpineComponent('craStep4', craStep4);
}

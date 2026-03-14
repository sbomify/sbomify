import { registerAlpineComponent } from '../../core/js/alpine-components';
import { getAssessmentId, saveStepAndNavigate } from './cra-shared';

interface ComponentStatus {
  component_id: string;
  component_name: string;
  has_sbom: boolean;
  sbom_format: string | null;
  bsi_status: string | null;
}

function craStep2() {
  return {
    assessmentId: '',
    components: [] as ComponentStatus[],
    summary: {} as Record<string, unknown>,
    isSaving: false,
    search: '',

    init() {
      const data = window.parseJsonScript('step-data') as Record<string, unknown> | null;
      if (data) {
        this.components = (data.components as ComponentStatus[]) || [];
        this.summary = (data.summary as Record<string, unknown>) || {};
      }
      this.assessmentId = getAssessmentId();
    },

    get filteredComponents(): ComponentStatus[] {
      if (!this.search) return this.components;
      const q = this.search.toLowerCase();
      return this.components.filter(c => c.component_name.toLowerCase().includes(q));
    },

    get totalComponents(): number {
      return this.components.length;
    },

    get componentsWithSbom(): number {
      return this.components.filter(c => c.has_sbom).length;
    },

    async markComplete(): Promise<void> {
      await saveStepAndNavigate(this.assessmentId, 2, {}, (v) => { this.isSaving = v; });
    },
  };
}

export function registerCraStep2(): void {
  registerAlpineComponent('craStep2', craStep2);
}

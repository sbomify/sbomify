import { registerAlpineComponent } from '../../core/js/alpine-components';
import { getAssessmentId, saveStepAndNavigate } from './cra-shared';

interface BSICheck {
  id: string;
  title: string;
  description: string;
  remediation: string;
}

interface BSIAssessment {
  status: string;
  pass_count: number;
  fail_count: number;
  warning_count: number;
  assessed_at: string | null;
  failing_checks: BSICheck[];
}

interface ComponentStatus {
  component_id: string;
  component_name: string;
  has_sbom: boolean;
  sbom_format: string | null;
  bsi_status: string | null;
  bsi_assessment: BSIAssessment | null;
}

function craStep2() {
  return {
    assessmentId: '',
    components: [] as ComponentStatus[],
    summary: {} as Record<string, unknown>,
    isSaving: false,
    search: '',
    expandedFixes: {} as Record<string, boolean>,

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

    hasFailingChecks(comp: ComponentStatus): boolean {
      return !!(comp.bsi_assessment?.failing_checks?.length);
    },

    toggleFixes(componentId: string): void {
      this.expandedFixes[componentId] = !this.expandedFixes[componentId];
    },

    isFixesExpanded(componentId: string): boolean {
      return !!this.expandedFixes[componentId];
    },

    async markComplete(): Promise<void> {
      await saveStepAndNavigate(this.assessmentId, 2, {}, (v) => { this.isSaving = v; });
    },
  };
}

export function registerCraStep2(): void {
  registerAlpineComponent('craStep2', craStep2);
}

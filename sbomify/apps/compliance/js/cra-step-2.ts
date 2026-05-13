import { registerAlpineComponent } from '../../core/js/alpine-components';
import { getAssessmentId, saveStepAndNavigate } from './cra-shared';

interface BSICheck {
  id: string;
  title: string;
  description: string;
  remediation: string;
  // Issue #907: classification of the finding so the wizard can
  // render "tooling limitation" vs "operator action" inline.
  remediation_type: 'operator_action' | 'tooling_limitation' | '';
  guidance_url: string;
  // One-line plain-English explanation of why this check fails in
  // practice (e.g. "syft doesn't emit SHA-512 for apt packages").
  // Populated from _BSI_HUMAN_SUMMARY server-side.
  human_summary: string;
  // Waiver overlay populated by _build_step_2_context when the
  // operator has accepted a tooling-limitation gap.
  waived?: boolean;
  justification?: string;
  waived_at?: string;
}

interface BSIAssessment {
  status: string;
  pass_count: number;
  fail_count: number;
  warning_count: number;
  assessed_at: string | null;
  failing_checks: BSICheck[];
  // Populated by wizard_service._build_step_2_context after
  // applying waivers — equals the count of ``failing_checks``
  // whose ``waived`` flag is false. The UI uses this (not
  // ``failing_checks.length``) to decide the pass/fail signal
  // so a component whose only failing checks are waived
  // tooling limitations renders as passing.
  unwaived_fail_count?: number;
}

interface ComponentStatus {
  component_id: string;
  component_name: string;
  component_url: string;
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
      // Raw predicate — true when there's any check in the
      // failing_checks list, regardless of waived state. The
      // "How to Fix" toggle and fixes panel use THIS so waived-
      // only components remain expandable and operators can still
      // review the waived findings + justifications for audit.
      return !!(comp.bsi_assessment?.failing_checks?.length);
    },

    hasUnwaivedFailures(comp: ComponentStatus): boolean {
      // Waiver-aware predicate — drives the pass/fail signal. Uses
      // the server-computed ``unwaived_fail_count`` (issue #907
      // waiver overlay) so a component whose only failing checks
      // are waived tooling limitations renders as passing. Falls
      // back to the max of the run's summary fail_count and the
      // per-finding list length when the overlay hasn't run —
      // taking the higher value ensures a truncated payload where
      // ``findings`` was dropped but ``summary`` survived doesn't
      // silently flip a failing component to green.
      const bsi = comp.bsi_assessment;
      if (!bsi) return false;
      if (typeof bsi.unwaived_fail_count === 'number') {
        return bsi.unwaived_fail_count > 0;
      }
      const summaryCount = typeof bsi.fail_count === 'number' ? bsi.fail_count : 0;
      const listCount = bsi.failing_checks?.length ?? 0;
      return Math.max(summaryCount, listCount) > 0;
    },

    hasWaivedChecks(comp: ComponentStatus): boolean {
      return (comp.bsi_assessment?.failing_checks || []).some(c => !!c.waived);
    },

    toggleFixes(componentId: string): void {
      const wasExpanded = !!this.expandedFixes[componentId];
      // Close all others — only one component's fixes visible at a time
      this.expandedFixes = {};
      if (!wasExpanded) {
        this.expandedFixes[componentId] = true;
      }
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

import { registerAlpineComponent } from '../../core/js/alpine-components';
import { getCsrfToken } from '../../core/js/csrf';
import { showError } from '../../core/js/alerts';
import { EU_COUNTRIES, EU_COUNTRY_NAMES } from './eu-countries';
import { getAssessmentId, saveStepAndNavigate } from './cra-shared';

interface Finding {
  finding_id: string;
  control_id: string;
  title: string;
  description: string;
  status: string;
  notes: string;
  justification: string;
  is_mandatory: boolean;
  annex_part: string;
  annex_reference: string;
  annex_url: string;
}

interface ControlGroup {
  group_id: string;
  group_title: string;
  controls: Finding[];
}

function craStep3() {
  return {
    assessmentId: '',
    activeTab: 'checklist' as 'checklist' | 'vulnerability' | 'incident',
    controlGroups: [] as ControlGroup[],
    summary: {} as Record<string, number>,
    expandedGroups: {} as Record<string, boolean>,
    vdpUrl: '',
    securityContactUrl: '',
    csirtContactEmail: '',
    acknowledgmentTimelineDays: null as number | null,
    csirtCountry: '',
    enisaSrpRegistered: false,
    incidentResponsePlanUrl: '',
    incidentResponseNotes: '',
    euCountries: EU_COUNTRIES,
    euCountryNames: EU_COUNTRY_NAMES,
    isSaving: false,
    _noteTimers: {} as Record<string, ReturnType<typeof setTimeout>>,
    _notesSaveStatus: {} as Record<string, 'saved' | 'failed' | 'saving'>,

    init() {
      const data = window.parseJsonScript('step-data') as Record<string, unknown> | null;
      if (data) {
        this.controlGroups = (data.control_groups as ControlGroup[]) || [];
        this.summary = (data.summary as Record<string, number>) || {};
        const vh = (data.vulnerability_handling as Record<string, unknown>) || {};
        this.vdpUrl = (vh.vdp_url as string) || '';
        this.securityContactUrl = (vh.security_contact_url as string) || '';
        this.csirtContactEmail = (vh.csirt_contact_email as string) || '';
        this.acknowledgmentTimelineDays = (vh.acknowledgment_timeline_days as number) || null;
        const art14 = (data.article_14 as Record<string, unknown>) || {};
        this.csirtCountry = (art14.csirt_country as string) || '';
        this.enisaSrpRegistered = !!(art14.enisa_srp_registered);
        this.incidentResponsePlanUrl = (art14.incident_response_plan_url as string) || '';
        this.incidentResponseNotes = (art14.incident_response_notes as string) || '';
        if (this.controlGroups.length > 0) {
          this.expandedGroups[this.controlGroups[0].group_id] = true;
        }
      }
      this.assessmentId = getAssessmentId();
    },

    destroy(): void {
      for (const key of Object.keys(this._noteTimers)) {
        clearTimeout(this._noteTimers[key]);
      }
    },

    toggleGroup(groupId: string): void {
      this.expandedGroups[groupId] = !this.expandedGroups[groupId];
    },

    isGroupExpanded(groupId: string): boolean {
      return !!this.expandedGroups[groupId];
    },

    groupCompletionCount(group: ControlGroup): string {
      const answered = group.controls.filter(c => c.status !== 'unanswered').length;
      return `${answered}/${group.controls.length}`;
    },

    async setFindingStatus(finding: Finding, status: string): Promise<void> {
      // Part II controls cannot be marked N/A (CRA Art 13(4))
      if (status === 'not-applicable' && finding.is_mandatory) return;

      const oldStatus = finding.status;
      finding.status = status;

      // Part I N/A requires justification — defer the PUT until the user fills it in,
      // then save via debouncedSaveNotes. Just update local status to reveal the textarea.
      if (status === 'not-applicable' && !finding.is_mandatory && !finding.justification?.trim()) {
        return;
      }

      try {
        const resp = await fetch(
          `/api/v1/compliance/cra/${this.assessmentId}/findings/${finding.finding_id}`,
          {
            method: 'PUT',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({
              status,
              notes: finding.notes,
              justification: finding.justification || '',
            }),
          },
        );
        if (!resp.ok) {
          finding.status = oldStatus;
          const err = await resp.json();
          showError(err.error || 'Failed to update');
        }
      } catch {
        finding.status = oldStatus;
        showError('Network error');
      }
    },

    debouncedSaveNotes(finding: Finding): void {
      const key = finding.finding_id;
      if (this._noteTimers[key]) {
        clearTimeout(this._noteTimers[key]);
      }
      this._notesSaveStatus[key] = 'saving';
      this._noteTimers[key] = setTimeout(() => {
        this.saveFindingNotes(finding);
      }, 800);
    },

    async saveFindingNotes(finding: Finding): Promise<void> {
      // Skip save if Part I N/A without justification — backend would reject with 400
      if (
        finding.status === 'not-applicable' &&
        !finding.is_mandatory &&
        !finding.justification?.trim()
      ) {
        this._notesSaveStatus[finding.finding_id] = 'saving';
        return;
      }
      try {
        const resp = await fetch(
          `/api/v1/compliance/cra/${this.assessmentId}/findings/${finding.finding_id}`,
          {
            method: 'PUT',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({
              status: finding.status,
              notes: finding.notes,
              justification: finding.justification || '',
            }),
          },
        );
        this._notesSaveStatus[finding.finding_id] = resp.ok ? 'saved' : 'failed';
      } catch {
        this._notesSaveStatus[finding.finding_id] = 'failed';
      }
    },

    get unansweredCount(): number {
      let count = 0;
      for (const group of this.controlGroups) {
        count += group.controls.filter(c => c.status === 'unanswered').length;
      }
      return count;
    },

    async save(): Promise<void> {
      if (this.isSaving) return;
      await saveStepAndNavigate(this.assessmentId, 3, {
        findings: [],
        vulnerability_handling: {
          vdp_url: this.vdpUrl,
          security_contact_url: this.securityContactUrl,
          csirt_contact_email: this.csirtContactEmail,
          acknowledgment_timeline_days: this.acknowledgmentTimelineDays,
        },
        article_14: {
          csirt_country: this.csirtCountry,
          enisa_srp_registered: this.enisaSrpRegistered,
          incident_response_plan_url: this.incidentResponsePlanUrl,
          incident_response_notes: this.incidentResponseNotes,
        },
      }, (v) => { this.isSaving = v; });
    },
  };
}

export function registerCraStep3(): void {
  registerAlpineComponent('craStep3', craStep3);
}

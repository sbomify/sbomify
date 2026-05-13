import { registerAlpineComponent } from '../../core/js/alpine-components';
import { getCsrfToken } from '../../core/js/csrf';
import { showError } from '../../core/js/alerts';
import { EU_COUNTRIES, EU_COUNTRY_NAMES } from './eu-countries';
import { getAssessmentId, saveStepAndNavigate } from './cra-shared';

export interface Finding {
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

export interface ControlGroup {
  group_id: string;
  group_title: string;
  controls: Finding[];
}

/**
 * Presentational status used by the three-button toggle. Derived from
 * `finding.status` + the client-only `_pendingNA` map; callers must not
 * re-implement this rule in the template to avoid the P1 duplication
 * footgun reported in the comprehensive review.
 */
export type FindingButtonState =
  | 'satisfied'
  | 'not-satisfied'
  | 'not-applicable'
  | 'pending-na'
  | 'unanswered';

export function craStep3() {
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
    _persistTimers: {} as Record<string, ReturnType<typeof setTimeout>>,
    _persistStatus: {} as Record<string, 'saved' | 'failed' | 'saving'>,
    _pendingNA: {} as Record<string, boolean>,

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
      for (const key of Object.keys(this._persistTimers)) {
        clearTimeout(this._persistTimers[key]);
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

      // Part I N/A without justification: reveal the justification textarea
      // via ``_pendingNA`` but leave ``finding.status`` untouched. Mutating
      // the local status here would make the group completion counter
      // count this control as "answered" even though the server still has
      // ``unanswered`` — reloading the page would flip it back and lose
      // the operator's intent.
      if (status === 'not-applicable' && !finding.is_mandatory && !finding.justification?.trim()) {
        this._pendingNA[finding.finding_id] = true;
        return;
      }

      // Any other status (or N/A with a justification) commits immediately.
      // Snapshot the rollback pair: `_pendingNA` flag and the prior status
      // must BOTH be restored on failure, otherwise the UI ends up in a
      // half-committed state (old status visible, pending marker gone).
      const wasPendingNA = !!this._pendingNA[finding.finding_id];
      const oldStatus = finding.status;
      delete this._pendingNA[finding.finding_id];
      finding.status = status;

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
          if (wasPendingNA) this._pendingNA[finding.finding_id] = true;
          const err = await resp.json();
          showError(err.error || 'Failed to update');
        }
      } catch {
        finding.status = oldStatus;
        if (wasPendingNA) this._pendingNA[finding.finding_id] = true;
        showError('Network error');
      }
    },

    /**
     * The single source of truth for "what colour is this finding's toggle".
     * Templates and tests both consume this instead of composing
     * ``finding.status`` + ``_pendingNA`` manually — the P1 review finding
     * was that three template sites duplicating the rule would silently
     * regress as new buttons/badges are added.
     */
    buttonState(finding: Finding): FindingButtonState {
      if (this._pendingNA[finding.finding_id]) return 'pending-na';
      switch (finding.status) {
        case 'satisfied':
        case 'not-satisfied':
        case 'not-applicable':
          return finding.status;
        default:
          return 'unanswered';
      }
    },

    showJustificationField(finding: Finding): boolean {
      return (
        !finding.is_mandatory &&
        (finding.status === 'not-applicable' || !!this._pendingNA[finding.finding_id])
      );
    },

    debouncedPersist(finding: Finding): void {
      const key = finding.finding_id;
      if (this._persistTimers[key]) {
        clearTimeout(this._persistTimers[key]);
      }
      this._persistStatus[key] = 'saving';
      this._persistTimers[key] = setTimeout(() => {
        this.persistFinding(finding);
      }, 800);
    },

    async persistFinding(finding: Finding): Promise<void> {
      const pendingNA = !!this._pendingNA[finding.finding_id];
      // Resolve the status to send. A pending Part I N/A only becomes
      // real when the operator has typed a justification. If
      // justification is still empty, PUT the existing (server-
      // persisted) status so the note the operator just typed still
      // gets saved — only the N/A transition is deferred, not the
      // note itself. Otherwise the operator can lose keystrokes by
      // navigating away before committing the N/A.
      let statusToSend = finding.status;
      if (pendingNA && finding.justification?.trim()) {
        statusToSend = 'not-applicable';
      }
      // Skip save if status is Part I N/A without justification — backend would reject with 400
      if (
        statusToSend === 'not-applicable' &&
        !finding.is_mandatory &&
        !finding.justification?.trim()
      ) {
        this._persistStatus[finding.finding_id] = 'failed';
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
              status: statusToSend,
              notes: finding.notes,
              justification: finding.justification || '',
            }),
          },
        );
        this._persistStatus[finding.finding_id] = resp.ok ? 'saved' : 'failed';
        if (resp.ok && pendingNA) {
          finding.status = statusToSend;
          delete this._pendingNA[finding.finding_id];
        }
      } catch {
        this._persistStatus[finding.finding_id] = 'failed';
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

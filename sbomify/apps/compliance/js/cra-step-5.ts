import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { registerAlpineComponent } from '../../core/js/alpine-components';
import { getCsrfToken } from '../../core/js/csrf';
import { showError, showSuccess } from '../../core/js/alerts';
import { getAssessmentId } from './cra-shared';

interface StepStatus {
  complete: boolean;
  controls?: {
    total: number;
    satisfied: number;
    'not-satisfied': number;
    'not-applicable': number;
    unanswered: number;
  };
  documents_generated?: number;
  documents_stale?: number;
}

interface ExportInfo {
  id: string;
  content_hash: string;
  created_at: string;
}

interface ComplianceSummary {
  product: { name: string; category: string; conformity_procedure: string };
  is_open_source_steward: boolean;
  steps: Record<string, StepStatus>;
  overall_ready: boolean;
  export_available: boolean;
  last_export: ExportInfo | null;
}

const DOC_KINDS = [
  { key: 'vdp', label: 'Vulnerability Disclosure Policy' },
  { key: 'security_txt', label: 'security.txt' },
  { key: 'risk_assessment', label: 'Risk Assessment' },
  { key: 'early_warning', label: 'Early Warning Notification' },
  { key: 'full_notification', label: 'Full Notification' },
  { key: 'final_report', label: 'Final Report' },
  { key: 'user_instructions', label: 'User Instructions' },
  { key: 'decommissioning_guide', label: 'Decommissioning Guide' },
  { key: 'declaration_of_conformity', label: 'Declaration of Conformity' },
];

interface DocStatus {
  exists: boolean;
  version: number;
  is_stale: boolean;
  generated_at: string;
}

function craStep5() {
  return {
    assessmentId: '',
    summary: {} as ComplianceSummary,
    steps: {} as Record<string, StepStatus>,
    documents: {} as Record<string, DocStatus>,
    lastExport: null as ExportInfo | null,
    overallReady: false,
    exportAvailable: false,
    docKinds: DOC_KINDS,
    isRefreshing: false,
    isExporting: false,
    isFinishing: false,
    generatingDoc: null as string | null,
    previewContent: '',
    showPreviewModal: false,
    previewTitle: '',
    isLoadingPreview: false,
    stepUrls: {} as Record<string, string>,

    init() {
      const data = window.parseJsonScript('step-data') as ComplianceSummary | null;
      if (data) {
        this.summary = data;
        this.steps = data.steps || {};
        this.lastExport = data.last_export || null;
        this.overallReady = !!(data.overall_ready);
        this.exportAvailable = !!(data.export_available);
      }
      this.assessmentId = getAssessmentId();
      this.stepUrls = (window.parseJsonScript('step-urls') as Record<string, string>) || {};
      this.loadStaleness();
    },

    async loadStaleness(): Promise<void> {
      try {
        // Fetch step 4 context which contains per-document status
        const resp = await fetch(`/api/v1/compliance/cra/${this.assessmentId}/step/4`);
        if (resp.ok) {
          const data = await resp.json();
          this.documents = (data.data?.documents as Record<string, DocStatus>) || {};
        }
      } catch {
        // Staleness check is best-effort
      }
    },

    getDocStatus(kind: string): string {
      const doc = this.documents[kind];
      if (!doc?.exists) return 'not_generated';
      if (doc.is_stale) return 'stale';
      return 'current';
    },

    get controlsSummary(): Record<string, number> {
      const step3 = this.steps['3'] as StepStatus | undefined;
      return (step3?.controls as Record<string, number>) || {};
    },

    get satisfiedCount(): number {
      return this.controlsSummary.satisfied || 0;
    },

    get totalControls(): number {
      return this.controlsSummary.total || 0;
    },

    get compliancePercent(): number {
      if (!this.totalControls) return 0;
      return Math.round((this.satisfiedCount / this.totalControls) * 100);
    },

    async previewDocument(kind: string, label: string): Promise<void> {
      this.previewTitle = label;
      this.isLoadingPreview = true;
      this.showPreviewModal = true;
      try {
        const resp = await fetch(
          `/api/v1/compliance/cra/${this.assessmentId}/documents/${kind}/preview`,
        );
        if (resp.ok) {
          const data = await resp.json();
          // marked.parse() is synchronous by default (async: false) so the
          // string cast is safe; add the option explicitly for clarity.
          const rawHtml = marked.parse(data.content || '', { async: false }) as string;
          this.previewContent = DOMPurify.sanitize(rawHtml);
        } else {
          showError('Failed to load preview');
          this.showPreviewModal = false;
        }
      } catch {
        showError('Network error');
        this.showPreviewModal = false;
      } finally {
        this.isLoadingPreview = false;
      }
    },

    async generateDocument(kind: string): Promise<void> {
      this.generatingDoc = kind;
      try {
        const resp = await fetch(
          `/api/v1/compliance/cra/${this.assessmentId}/generate/${kind}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
          },
        );
        if (resp.ok) {
          showSuccess('Document generated');
          await this.loadStaleness();
        } else {
          const err = await resp.json();
          showError(err.error || 'Failed to generate');
        }
      } catch {
        showError('Network error');
      } finally {
        this.generatingDoc = null;
      }
    },

    async refreshStale(): Promise<void> {
      this.isRefreshing = true;
      try {
        const resp = await fetch(
          `/api/v1/compliance/cra/${this.assessmentId}/refresh`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
          },
        );
        if (resp.ok) {
          const data = await resp.json();
          showSuccess(`${data.refreshed_count} document(s) refreshed`);
          await this.loadStaleness();
        } else {
          showError('Failed to refresh');
        }
      } catch {
        showError('Network error');
      } finally {
        this.isRefreshing = false;
      }
    },

    async exportBundle(): Promise<void> {
      this.isExporting = true;
      try {
        const resp = await fetch(
          `/api/v1/compliance/cra/${this.assessmentId}/export`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
          },
        );
        if (resp.ok) {
          const pkg = await resp.json();
          const dlResp = await fetch(
            `/api/v1/compliance/cra/${this.assessmentId}/export/${pkg.id}/download`,
            { headers: { 'X-CSRFToken': getCsrfToken() } },
          );
          if (dlResp.ok) {
            const dl = await dlResp.json();
            window.open(dl.download_url, '_blank', 'noopener,noreferrer');
            showSuccess('Export package ready');
          } else {
            showError('Failed to get download URL');
          }
        } else {
          const err = await resp.json();
          showError(err.error || 'Failed to export');
        }
      } catch {
        showError('Network error');
      } finally {
        this.isExporting = false;
      }
    },

    async finishAssessment(): Promise<void> {
      this.isFinishing = true;
      try {
        const resp = await fetch(`/api/v1/compliance/cra/${this.assessmentId}/step/5`, {
          method: 'PATCH',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
          body: JSON.stringify({ data: {} }),
        });
        if (resp.ok) {
          showSuccess('Assessment marked as complete');
          window.location.reload();
        } else {
          const err = await resp.json();
          showError(err.error || 'Cannot complete yet');
        }
      } catch {
        showError('Network error');
      } finally {
        this.isFinishing = false;
      }
    },
  };
}

export function registerCraStep5(): void {
  registerAlpineComponent('craStep5', craStep5);
}

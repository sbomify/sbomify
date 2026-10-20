import { formatNumber } from '../../core/js/number-format';
import { formatDate } from '../../core/js/utils';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { registerAlpineComponent } from '../../core/js/alpine-components';
import { getCsrfToken } from '../../core/js/csrf';
import { showError, showSuccess } from '../../core/js/alerts';
import { getAssessmentId } from './cra-shared';
import { shellQuote } from '../../core/js/components/repository-setup';

interface StepStatus {
  complete: boolean;
  /** Why the EU-representation block is not settled, if it is not. A step can
   *  be complete and still carry one: the establishment determination is
   *  recorded rather than demanded, and it blocks the export instead. */
  eu_representation_problems?: string[];
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

interface ExportFileEntry {
  path: string;
  sha256: string;
  cra_reference: string;
}

interface ExportIntegrity {
  hash_algorithm: string;
  manifest_hash_file: string;
  verification_doc: string;
}

/** The manufacturer's keyless Sigstore signature over the ZIP, verified on upload. */
interface ExportSignature {
  signed_by: string;
  issuer: string;
  signed_at: string;
}

interface ExportInfo {
  id: string;
  content_hash: string;
  created_at: string;
  format_version?: string | null;
  manufacturer_is_placeholder?: boolean;
  integrity?: ExportIntegrity | null;
  files?: ExportFileEntry[];
  file_name?: string;
  signature?: ExportSignature | null;
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

// The OIDC issuers a manufacturer is likely to sign keyless through.
const SIGNER_ISSUERS = [
  { value: 'https://github.com/login/oauth', label: 'GitHub' },
  { value: 'https://accounts.google.com', label: 'Google' },
  { value: 'https://login.microsoftonline.com', label: 'Microsoft' },
  { value: 'https://token.actions.githubusercontent.com', label: 'GitHub Actions' },
  { value: 'https://gitlab.com', label: 'GitLab' },
];

interface DocStatus {
  exists: boolean;
  version: number;
  is_stale: boolean;
  generated_at: string;
}

export function craStep5() {
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
    signerIssuers: SIGNER_ISSUERS,
    signForm: { identity: '', issuer: SIGNER_ISSUERS[0].value },
    signFile: null as File | null,
    isSigning: false,
    isFinishing: false,
    generatingDoc: null as string | null,
    previewContent: '',
    showPreviewModal: false,
    previewTitle: '',
    isLoadingPreview: false,
    downloadingDocPdf: false,
    stepUrls: {} as Record<string, string>,
    // Named reasons the export is refused, for when "complete every step" is
    // not the reason and saying so sends the reader to look in the wrong place.
    blockers: [] as string[],

    init() {
      const data = window.parseJsonScript('step-data') as ComplianceSummary | null;
      if (data) {
        this.summary = data;
        this.steps = data.steps || {};
        this.lastExport = data.last_export || null;
        this.overallReady = !!(data.overall_ready);
        this.exportAvailable = !!(data.export_available);
        this.blockers = Object.values(data.steps || {})
          .flatMap((s) => s.eu_representation_problems || []);
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

    /**
     * Download an on-demand PDF rendering of a CRA document.
     *
     * The endpoint streams ``application/pdf`` with
     * ``Content-Disposition: attachment``, so we pass the response
     * blob through ``URL.createObjectURL`` and trigger a synthetic
     * anchor click to land it in the user's Downloads folder. Done
     * via fetch (rather than a plain ``<a href=...>``) so we can
     * surface a 503 ``pdf_renderer_unavailable`` error inline as a
     * toast — the renderer is best-effort in distroless prod.
     */
    async downloadDocumentPdf(kind: string, label: string): Promise<void> {
      if (this.downloadingDocPdf) return;
      this.downloadingDocPdf = true;
      try {
        const resp = await fetch(
          `/api/v1/compliance/cra/${this.assessmentId}/documents/${kind}/download`,
        );
        if (!resp.ok) {
          let message = `Failed to download ${label} PDF`;
          try {
            const err = await resp.json();
            if (err?.error) message = err.error;
          } catch {
            /* non-JSON error payload — keep default */
          }
          showError(message);
          return;
        }
        const blob = await resp.blob();
        const headerName = resp.headers.get('Content-Disposition') || '';
        const match = headerName.match(/filename="?([^";]+)"?/);
        const filename = match?.[1] || `${kind}.pdf`;
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        showSuccess(`${label} PDF downloaded.`);
      } catch {
        showError('Network error while downloading PDF');
      } finally {
        this.downloadingDocPdf = false;
      }
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
          showSuccess(`${formatNumber(data.refreshed_count)} document(s) refreshed`);
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
          await this.loadExport(pkg.id);
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

    // A signature is checked against one ZIP's hash, so after an export the
    // card and the signing form must describe the ZIP that was downloaded: not
    // the one the page loaded with, and not a newer one someone else made.
    // Until it loads, nothing is offered for signing.
    async loadExport(packageId: string): Promise<void> {
      this.lastExport = null;
      this.signFile = null;
      const resp = await fetch(`/api/v1/compliance/cra/${this.assessmentId}/export/${packageId}`, {
        headers: { 'X-CSRFToken': getCsrfToken() },
      });
      if (!resp.ok) {
        showError('The export is ready, but this page could not load it. Reload the page to sign it.');
        return;
      }
      this.lastExport = await resp.json();
    },

    get signCommand(): string {
      const file = this.lastExport?.file_name || '<bundle>.zip';
      return `cosign sign-blob ${file} --bundle ${file}.sigstore.json`;
    },

    get verifyCommand(): string {
      const file = this.lastExport?.file_name || '<bundle>.zip';
      const sig = this.lastExport?.signature;
      return (
        `cosign verify-blob ${file} --bundle ${file}.sigstore.json` +
        // A workflow identity can carry &, ; or $( in its git ref.
        ` --certificate-identity ${sig ? shellQuote(sig.signed_by) : '<signer>'}` +
        ` --certificate-oidc-issuer ${sig ? shellQuote(sig.issuer) : '<issuer>'}`
      );
    },

    issuerLabel(issuer: string): string {
      return SIGNER_ISSUERS.find((i) => i.value === issuer)?.label ?? issuer;
    },

    signedOn(signedAt: string): string {
      return formatDate(signedAt);
    },

    pickSignatureFile(event: Event): void {
      this.signFile = (event.target as HTMLInputElement).files?.[0] ?? null;
    },

    async uploadSignature(): Promise<void> {
      if (!this.lastExport || !this.signFile || this.isSigning) return;
      let bundle: unknown;
      try {
        bundle = JSON.parse(await this.signFile.text());
      } catch {
        showError('This file is not a Sigstore bundle.');
        return;
      }
      const packageId = this.lastExport.id;
      this.isSigning = true;
      try {
        const resp = await fetch(
          `/api/v1/compliance/cra/${this.assessmentId}/export/${packageId}/signature`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({
              bundle,
              identity: this.signForm.identity.trim(),
              issuer: this.signForm.issuer,
            }),
          },
        );
        const body = await resp.json().catch(() => ({}));
        if (resp.ok) {
          // A new export can replace the card while the signature is checked.
          if (this.lastExport?.id === packageId) {
            this.lastExport = { ...this.lastExport, signature: body as ExportSignature };
          }
          showSuccess('Signature verified and saved');
        } else {
          showError(body.error || 'Failed to upload the signature');
        }
      } catch {
        showError('Network error');
      } finally {
        this.isSigning = false;
      }
    },

    // The signature URL is presigned for 15 minutes, so each click asks for a
    // fresh one rather than keeping it.
    async downloadSignature(): Promise<void> {
      if (!this.lastExport?.signature) return;
      try {
        const resp = await fetch(
          `/api/v1/compliance/cra/${this.assessmentId}/export/${this.lastExport.id}/download`,
          { headers: { 'X-CSRFToken': getCsrfToken() } },
        );
        const dl = resp.ok ? await resp.json() : null;
        if (dl?.signature_url) {
          window.open(dl.signature_url, '_blank', 'noopener,noreferrer');
        } else {
          showError('Failed to get the signature download URL');
        }
      } catch {
        showError('Network error');
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

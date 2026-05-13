import { registerAlpineComponent } from '../../core/js/alpine-components';
import { getCsrfToken } from '../../core/js/csrf';
import { showError } from '../../core/js/alerts';

/**
 * CRA Scope Screening — pre-wizard gate to determine if CRA applies.
 *
 * Based on FAQ Section 1 (CRA Art 2-3, Art 21).
 */
interface ScreeningUrls {
  save: string;
  start_assessment: string;
}

function craScopeScreening() {
  return {
    hasDataConnection: true,
    isOwnUseOnly: false,
    isTestingVersion: false,
    isCoveredByOtherLegislation: false,
    exemptedLegislationName: '',
    isDualUse: false,
    screeningNotes: '',
    isSaving: false,
    // Server-resolved URLs, injected via ``json_script:"screening-urls"``
    // so the POST target doesn't come from ``window.location.href``
    // (which would inherit a potentially attacker-controlled ``Host``).
    urls: { save: '', start_assessment: '' } as ScreeningUrls,

    init() {
      const data = window.parseJsonScript('screening-data');
      if (data) {
        const d = data as Record<string, unknown>;
        this.hasDataConnection = d.has_data_connection !== false;
        this.isOwnUseOnly = !!(d.is_own_use_only);
        this.isTestingVersion = !!(d.is_testing_version);
        this.isCoveredByOtherLegislation = !!(d.is_covered_by_other_legislation);
        this.exemptedLegislationName = (d.exempted_legislation_name as string) || '';
        this.isDualUse = !!(d.is_dual_use);
        this.screeningNotes = (d.screening_notes as string) || '';
      }
      const urls = window.parseJsonScript('screening-urls') as ScreeningUrls | null;
      if (urls && urls.save && urls.start_assessment) {
        this.urls = urls;
      }
    },

    /** Whether CRA applies based on current answers (FAQ 1.1). */
    get craApplies(): boolean {
      if (!this.hasDataConnection) return false;
      if (this.isOwnUseOnly) return false;
      if (this.isCoveredByOtherLegislation) return false;
      return true;
    },

    /** Human-readable reason for scope exclusion. */
    get scopeExclusion(): string {
      if (!this.hasDataConnection) {
        return 'Product has no data connection capability (CRA Art 3(1), FAQ 1.1).';
      }
      if (this.isOwnUseOnly) {
        return 'Product is for own use only, not placed on the EU market (CRA Art 2(1), FAQ 1.5).';
      }
      if (this.isCoveredByOtherLegislation) {
        return `Product is covered by exempted EU legislation: ${this.exemptedLegislationName || '(not specified)'} (CRA Art 2(3-5), FAQ 1.9).`;
      }
      return '';
    },

    async submit(): Promise<void> {
      if (this.isSaving) return;
      if (!this.urls.save) {
        showError('Scope-screening URL not configured; refresh the page.');
        return;
      }
      this.isSaving = true;

      try {
        const resp = await fetch(this.urls.save, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
          body: JSON.stringify({
            has_data_connection: this.hasDataConnection,
            is_own_use_only: this.isOwnUseOnly,
            is_testing_version: this.isTestingVersion,
            is_covered_by_other_legislation: this.isCoveredByOtherLegislation,
            exempted_legislation_name: this.exemptedLegislationName,
            is_dual_use: this.isDualUse,
            screening_notes: this.screeningNotes,
          }),
        });

        if (!resp.ok) {
          const text = await resp.text();
          showError(text || 'Failed to save screening');
          return;
        }

        const result = await resp.json();
        // Trust the server-resolved start URL, not the ``redirect``
        // the server echoes back. Same defence as the save URL — keep
        // all navigation targets server-resolved so no request header
        // can steer the form submission off-origin.
        if (result.cra_applies && this.urls.start_assessment) {
          const form = document.createElement('form');
          form.method = 'POST';
          form.action = this.urls.start_assessment;
          const csrf = document.createElement('input');
          csrf.type = 'hidden';
          csrf.name = 'csrfmiddlewaretoken';
          csrf.value = getCsrfToken();
          form.appendChild(csrf);
          document.body.appendChild(form);
          form.submit();
        }
        // If CRA doesn't apply, stay on page — result is shown
      } catch {
        showError('Network error');
      } finally {
        this.isSaving = false;
      }
    },
  };
}

export function registerCraScopeScreening(): void {
  registerAlpineComponent('craScopeScreening', craScopeScreening);
}

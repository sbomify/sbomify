/**
 * Manufacturer-signature pad for the CRA Declaration of Conformity.
 *
 * Captures Place / Name / Function as plain text plus a drawn
 * signature, persists them to ``PUT /api/v1/compliance/cra/<id>/signature``,
 * and pre-fills from a prior save so the operator can re-sign in
 * place. The signature image goes over the wire as a base64-encoded
 * PNG data URL produced by ``signature_pad`` — the API enforces a
 * size cap and a strict ``data:image/png;base64,`` prefix check.
 *
 * Saving deliberately marks the existing DoC ``CRAGeneratedDocument``
 * as stale rather than auto-regenerating; the operator confirms by
 * clicking "Generate Declaration of Conformity" afterwards. The
 * "Refresh Stale Documents" button picks the change up automatically.
 */
import SignaturePad from 'signature_pad';

import { registerAlpineComponent } from '../../core/js/alpine-components';
import { showError, showSuccess } from '../../core/js/alerts';
import { getCsrfToken } from '../../core/js/csrf';
import { getAssessmentId } from './cra-shared';

interface SignatureResponse {
  place: string;
  name: string;
  function: string;
  image: string;
  signed_at: string | null;
  is_signed: boolean;
}

interface ApiError {
  error?: string;
  error_code?: string;
}

function craDocSignature() {
  return {
    assessmentId: '',
    pad: null as SignaturePad | null,
    place: '',
    name: '',
    roleFunction: '',
    image: '',
    signedAt: null as string | null,
    isSigned: false,
    isSaving: false,
    isLoading: true,

    async init(): Promise<void> {
      this.assessmentId = getAssessmentId();
      // Wait one tick so the canvas has finished its layout pass — instantiating
      // ``SignaturePad`` against a 0×0 canvas leaves it in a state where the
      // first stroke draws as a dot, which is confusing UX.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const self = this as any;
      await self.$nextTick();
      const canvas = self.$refs.canvas as HTMLCanvasElement | undefined;
      if (canvas) {
        this._fitCanvas(canvas);
        this.pad = new SignaturePad(canvas, {
          minWidth: 0.6,
          maxWidth: 2.0,
          backgroundColor: 'rgb(255, 255, 255)',
        });
      }
      await this._load();
      this.isLoading = false;
    },

    /**
     * Resize the canvas's internal pixel buffer to match the laid-out
     * size at the current devicePixelRatio. Without this the ink looks
     * blurry on retina displays and the pad's coordinate space drifts
     * relative to the cursor.
     */
    _fitCanvas(canvas: HTMLCanvasElement): void {
      const ratio = Math.max(window.devicePixelRatio || 1, 1);
      canvas.width = canvas.offsetWidth * ratio;
      canvas.height = canvas.offsetHeight * ratio;
      const ctx = canvas.getContext('2d');
      if (ctx) ctx.scale(ratio, ratio);
    },

    async _load(): Promise<void> {
      try {
        const resp = await fetch(`/api/v1/compliance/cra/${this.assessmentId}/signature`);
        if (!resp.ok) {
          // 404/403 here just means there's nothing to pre-fill.
          return;
        }
        const data = (await resp.json()) as SignatureResponse;
        this.place = data.place || '';
        this.name = data.name || '';
        // ``function`` is a reserved JS word; locally we use ``roleFunction``
        // so ``x-model="..."`` Alpine expressions don't choke. The wire
        // payload still uses ``function`` so the API key matches CRA Annex V.
        this.roleFunction = data.function || '';
        this.image = data.image || '';
        this.signedAt = data.signed_at;
        this.isSigned = data.is_signed;
        // Restore the strokes so the pad reflects the prior save.
        if (data.image && this.pad) {
          this.pad.fromDataURL(data.image, { ratio: 1 });
        }
      } catch {
        // Network blip — leave the form empty, operator can still sign.
      }
    },

    clearPad(): void {
      this.pad?.clear();
      this.image = '';
    },

    async save(): Promise<void> {
      if (this.isSaving) return;
      if (!this.place.trim() || !this.name.trim() || !this.roleFunction.trim()) {
        showError('Place, name, and function are all required.');
        return;
      }
      if (!this.pad || this.pad.isEmpty()) {
        showError('Please draw your signature before saving.');
        return;
      }

      const image = this.pad.toDataURL('image/png');

      this.isSaving = true;
      try {
        const resp = await fetch(`/api/v1/compliance/cra/${this.assessmentId}/signature`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
          body: JSON.stringify({
            place: this.place.trim(),
            name: this.name.trim(),
            function: this.roleFunction.trim(),
            image,
          }),
        });
        if (resp.ok) {
          const data = (await resp.json()) as SignatureResponse;
          this.image = data.image;
          this.signedAt = data.signed_at;
          this.isSigned = data.is_signed;
          showSuccess(
            'Signature saved. Click "Generate Declaration of Conformity" to refresh the rendered DoC.',
          );
        } else {
          const err = (await resp.json().catch(() => ({}))) as ApiError;
          showError(err.error || 'Failed to save signature.');
        }
      } catch {
        showError('Network error while saving signature.');
      } finally {
        this.isSaving = false;
      }
    },
  };
}

export function registerCraDocSignature(): void {
  registerAlpineComponent('craDocSignature', craDocSignature);
}

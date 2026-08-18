import { registerAlpineComponent } from '../../core/js/alpine-components';
import { getCsrfToken } from '../../core/js/csrf';

interface CiTokenResponse {
  token: string;
  expires_at: string;
  lifetime_days: number;
}

/**
 * The mint-a-token half of the CI/CD dialog.
 *
 * Lives here rather than in an `x-data` attribute because the command it sits
 * beside contains shell quotes and newlines, and djlint collapses long
 * attributes onto one line — which silently turns a `//` comment into a comment
 * over everything after it.
 *
 * Nothing is minted when the dialog opens. Reading the command is not a
 * decision to create a credential.
 */
export function ciCdToken(mintUrl: string) {
  return {
    token: '',
    expiresAt: '',
    minting: false,
    error: '',

    async mint(): Promise<void> {
      // Guard the double-click as well as the disabled attribute: a second
      // request would leave a live token nobody ever sees.
      if (this.minting || this.token) return;
      this.minting = true;
      this.error = '';
      try {
        const response = await fetch(mintUrl, {
          method: 'POST',
          headers: { 'X-CSRFToken': getCsrfToken() },
        });
        if (!response.ok) throw new Error(String(response.status));
        const data = (await response.json()) as CiTokenResponse;
        this.token = data.token;
        // Explicit parts rather than the locale default: that renders 14/08/2026
        // in one locale and 08/14/2026 in another, and an expiry date a reader
        // can misread by six months is worse than no date.
        this.expiresAt = new Date(data.expires_at).toLocaleDateString(undefined, {
          year: 'numeric',
          month: 'short',
          day: 'numeric',
        });
      } catch {
        this.error = 'Could not create a token. Create one in Settings → API tokens instead.';
      } finally {
        this.minting = false;
      }
    },
  };
}

export function registerCiCdToken(): void {
  registerAlpineComponent('ciCdToken', ciCdToken);
}

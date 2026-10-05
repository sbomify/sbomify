import Alpine from 'alpinejs';

interface VisibilitySelectorParams {
  itemType: string;
  itemId: string;
  currentVisibility: string;
  gatedVisibilityAllowed: boolean;
  preview?: boolean;
}

const visibilityOptions = {
  private: { label: 'Private', icon: 'fas fa-lock' },
  public: { label: 'Public', icon: 'fas fa-globe' },
  gated: { label: 'Gated', icon: 'fas fa-shield-halved' },
};

type Visibility = keyof typeof visibilityOptions;

function isVisibility(value: unknown): value is Visibility {
  return value === 'private' || value === 'public' || value === 'gated';
}

/** Keep the saved choice until the existing visibility endpoint accepts a change. */
export function registerVisibilitySelector(): void {
  Alpine.data('visibilitySelector', ({
    itemType, itemId, currentVisibility, gatedVisibilityAllowed, preview = false,
  }: VisibilitySelectorParams) => ({
    visibility: isVisibility(currentVisibility) ? currentVisibility : 'private',
    pendingVisibility: currentVisibility,
    isLoading: false,

    get statusIcon(): string {
      return visibilityOptions[this.visibility].icon;
    },
    get statusText(): string {
      return visibilityOptions[this.visibility].label;
    },

    selectVisibility(value: Visibility): void {
      if (this.isLoading || value === this.visibility || (value === 'gated' && !gatedVisibilityAllowed)) return;
      if (preview) {
        this.visibility = value;
        return;
      }
      this.pendingVisibility = value;
      this.$nextTick(() => (this.$refs.form as HTMLFormElement).requestSubmit());
    },

    afterRequest(event: CustomEvent): void {
      this.isLoading = false;
      try {
        const response = JSON.parse(event.detail.xhr.responseText);
        const value = itemType === 'product'
          ? typeof response.is_public === 'boolean' ? response.is_public ? 'public' : 'private' : null
          : response.visibility;
        if (!event.detail.successful || !isVisibility(value)) return;
        this.visibility = value;
        window.dispatchEvent(new CustomEvent('public-status-changed', {
          detail: itemType === 'product'
            ? { itemType, itemId, isPublic: value === 'public' }
            : { itemType, itemId, visibility: value },
        }));
      } catch {
        // Error and expired-session responses leave the saved choice intact.
      } finally {
        this.pendingVisibility = this.visibility;
      }
    },
  }));
}

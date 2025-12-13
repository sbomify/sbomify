import Alpine from 'alpinejs';
import { showSuccess, showError } from '../alerts';

interface PublicStatusToggleParams {
  itemType: string
  itemId: string
  publicUrl: string
  isPublic: boolean
}

export function registerPublicStatusToggle() {
  Alpine.data('publicStatusToggle', ({ itemType, itemId, publicUrl, isPublic }: PublicStatusToggleParams) => {
    return {
      itemType,
      itemId,
      publicUrl,
      isPublic,
      isLoading: false,

      get showInheritanceNote(): boolean {
        return this.itemType === 'release'
      },

      get statusIcon(): string {
        return this.isPublic ? 'fas fa-globe' : 'fas fa-lock'
      },

      get statusText(): string {
        return this.isPublic ? 'Public' : 'Private'
      },

      togglePublicStatus(): void {
        this.isPublic = !this.isPublic
      },

      beforeRequestHandler(): void {
        this.isLoading = true
      },

      afterRequestHandler(event: CustomEvent): void {
        this.isLoading = false

        const response = JSON.parse(event.detail.xhr.response)

        if (!('is_public' in response)) {
          this.isPublic = !this.isPublic
          return
        }
        this.isPublic = response.is_public
      },

      async copyToClipboard(): Promise<void> {
        try {
          await navigator.clipboard.writeText(new URL(this.publicUrl, window.location.origin).href)
          showSuccess('Public URL copied to clipboard')
        } catch (error) {
          console.error('Failed to copy to clipboard:', error)
          showError('Failed to copy URL to clipboard')
        }
      },
    }
  })
}

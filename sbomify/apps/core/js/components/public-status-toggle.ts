import Alpine from 'alpinejs';
import { publicSharing } from './public-sharing';

interface PublicStatusToggleParams {
  itemType: string
  itemId: string
  publicUrl: string
  isPublic: boolean
}

export function registerPublicStatusToggle() {
  Alpine.data('publicStatusToggle', ({ itemType, itemId, publicUrl, isPublic }: PublicStatusToggleParams) => {
    return {
      ...publicSharing(publicUrl),
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

        // Components use visibility; products use is_public
        if (this.itemType === 'component') {
          if (!('visibility' in response)) {
            this.isPublic = !this.isPublic
            return
          }
          this.isPublic = response.visibility === 'public'
        } else {
          if (!('is_public' in response)) {
            this.isPublic = !this.isPublic
            return
          }
          this.isPublic = response.is_public
        }

        window.dispatchEvent(new CustomEvent('public-status-changed', {
          detail: { itemType: this.itemType, itemId: this.itemId, isPublic: this.isPublic }
        }))
      },

    }
  })
}

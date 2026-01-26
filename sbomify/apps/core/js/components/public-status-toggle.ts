import Alpine from 'alpinejs';
import { showSuccess, showError } from '../alerts';

interface PublicStatusToggleParams {
  itemType: string
  itemId: string
  publicUrl: string
  isPublic: boolean
}

export function registerPublicStatusToggle(): void {
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

        // Components use visibility, products/projects use is_public
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

      async copyToClipboard(): Promise<void> {
        try {
          await navigator.clipboard.writeText(new URL(this.publicUrl, window.location.origin).href)
          showSuccess('Public URL copied to clipboard')
        } catch (error) {
          console.error('Failed to copy to clipboard:', error)
          showError('Failed to copy URL to clipboard')
        }
      },

      copyBadgeToClipboard(): void {
        const badgeSvgUrl = 'https://sbomify.com/assets/images/logo/badge.svg'
        const publicUrl = new URL(this.publicUrl, window.location.origin).href
        const markdown = `[![sbomified](${badgeSvgUrl})](${publicUrl})`

        navigator.clipboard.writeText(markdown).then(() => {
          this.$dispatch('messages', {
            value: [{ type: 'success', message: 'Badge markdown copied to clipboard' }]
          })
        }).catch(err => {
          console.error('Failed to copy badge:', err)
          this.$dispatch('messages', {
            value: [{ type: 'error', message: 'Failed to copy badge to clipboard' }]
          })
        })
      },
    }
  })
}

import Alpine from 'alpinejs';
import { showSuccess, showError } from '../alerts';

interface ComponentVisibilitySelectorParams {
  itemId: string
  publicUrl: string
  currentVisibility: string
  gatedVisibilityAllowed: boolean
}

export function registerComponentVisibilitySelector(): void {
  Alpine.data('componentVisibilitySelector', ({ 
    itemId, 
    publicUrl, 
    currentVisibility, 
    gatedVisibilityAllowed 
  }: ComponentVisibilitySelectorParams) => {
    const initialVisibility = currentVisibility || 'private'
    return {
      itemId,
      publicUrl,
      visibility: initialVisibility,
      gatedVisibilityAllowed,
      isLoading: false,
      initialVisibility,

      get statusIcon(): string {
        switch (this.visibility) {
          case 'public':
            return 'fas fa-globe'
          case 'gated':
            return 'fas fa-shield-alt'
          case 'private':
          default:
            return 'fas fa-lock'
        }
      },

      get statusText(): string {
        switch (this.visibility) {
          case 'public':
            return 'Public'
          case 'gated':
            return 'Gated'
          case 'private':
          default:
            return 'Private'
        }
      },

      getAllVisibilityInfo(): string {
        let info = '<div class="visibility-info-tooltip">'
        info += '<div class="mb-2"><strong>Public:</strong> Anyone can view and download</div>'
        info += '<div class="mb-2"><strong>Private:</strong> Only team members can access</div>'
        if (this.gatedVisibilityAllowed) {
          info += '<div><strong>Gated:</strong> Visible to all, but requires approval to download</div>'
        }
        info += '</div>'
        return info
      },

      initTooltips(): void {
        // Alpine tooltips are auto-initialized from x-tooltip attributes
        // This method is kept for compatibility but no longer needed
        // Tooltips should be set via x-tooltip.html in the template
      },


      beforeRequestHandler(): void {
        this.isLoading = true
      },

      afterRequestHandler(event: CustomEvent): void {
        this.isLoading = false

        try {
          const response = JSON.parse(event.detail.xhr.response)

          if (!('visibility' in response)) {
            // Revert on error
            this.visibility = this.initialVisibility
            return
          }

          this.visibility = response.visibility
          this.initialVisibility = this.visibility // Update initial for future error recovery

          window.dispatchEvent(new CustomEvent('public-status-changed', {
            detail: { itemType: 'component', itemId: this.itemId, visibility: this.visibility }
          }))
        } catch (error) {
          console.error('Failed to parse response:', error)
          // Revert on parse error
          this.visibility = this.initialVisibility
        }
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
      }
    }
  })
}

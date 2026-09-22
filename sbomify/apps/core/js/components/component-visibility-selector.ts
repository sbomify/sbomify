import Alpine from 'alpinejs';

interface ComponentVisibilitySelectorParams {
  itemId: string
  currentVisibility: string
  gatedVisibilityAllowed: boolean
}

export function registerComponentVisibilitySelector() {
  Alpine.data('componentVisibilitySelector', ({ 
    itemId, 
    currentVisibility, 
    gatedVisibilityAllowed 
  }: ComponentVisibilitySelectorParams) => {
    const initialVisibility = currentVisibility || 'private'
    return {
      itemId,
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
        // Bootstrap tooltips removed - functionality not critical for component visibility selector
        // HTML tooltips were previously used to show visibility info
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

    }
  })
}

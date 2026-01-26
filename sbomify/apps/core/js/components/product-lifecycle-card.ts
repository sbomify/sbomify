import Alpine from 'alpinejs';

interface ProductLifecycleCardData {
    editing: boolean;
    releaseDate: string;
    endOfSupport: string;
    endOfLife: string;
    saving: boolean;
    initialReleaseDate: string;
    initialEndOfSupport: string;
    initialEndOfLife: string;
    productId: number;
    cardElementId: string;
    updateUrl: string;
    csrfToken: string;
    $el: HTMLElement;
    saveLifecycle: () => Promise<void>;
    cancelEdit: () => void;
}

/**
 * Product Lifecycle Card Component
 * Handles editing and saving product lifecycle dates
 */
export function registerProductLifecycleCard(): void {
    Alpine.data('productLifecycleCard', ({
        productId,
        cardElementId,
        updateUrl,
        csrfToken,
        initialReleaseDate,
        initialEndOfSupport,
        initialEndOfLife
    }: {
        productId: number;
        cardElementId: string;
        updateUrl: string;
        csrfToken: string;
        initialReleaseDate: string;
        initialEndOfSupport: string;
        initialEndOfLife: string;
    }): ProductLifecycleCardData => {
        return {
            editing: false,
            releaseDate: initialReleaseDate,
            endOfSupport: initialEndOfSupport,
            endOfLife: initialEndOfLife,
            saving: false,
            initialReleaseDate,
            $el: {} as HTMLElement, // Will be set by Alpine
            initialEndOfSupport,
            initialEndOfLife,
            productId,
            cardElementId,
            updateUrl,
            csrfToken,
            
            async saveLifecycle() {
                this.saving = true;
                const formData = new FormData();
                formData.append('release_date', this.releaseDate || '');
                formData.append('end_of_support', this.endOfSupport || '');
                formData.append('end_of_life', this.endOfLife || '');
                
                try {
                    const response = await fetch(this.updateUrl, {
                        method: 'POST',
                        headers: {
                            'X-CSRFToken': this.csrfToken
                        },
                        body: formData
                    });
                    
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    
                    const html = await response.text();
                    const cardElement = document.getElementById(this.cardElementId);
                    if (cardElement) {
                        cardElement.outerHTML = html;
                        // Re-initialize Alpine on the new content
                        if (window.Alpine) {
                            window.Alpine.initTree(cardElement.parentElement || document.body);
                        }
                    }
                } catch (error) {
                    console.error('Error saving lifecycle:', error);
                    this.saving = false;
                }
            },
            
            cancelEdit() {
                this.editing = false;
                this.releaseDate = this.initialReleaseDate;
                this.endOfSupport = this.initialEndOfSupport;
                this.endOfLife = this.initialEndOfLife;
            }
        };
    });
}

/**
 * Workspace Integrations TypeScript
 * Handles vulnerability scanning provider selection and server configuration
 */

// VulnerabilitySettings interface removed - defined elsewhere if needed

class IntegrationsManager {
    private selectedProvider: HTMLInputElement | null;
    private selectedServer: HTMLInputElement | null;

    constructor() {
        this.selectedProvider = document.getElementById('selectedProvider') as HTMLInputElement;
        this.selectedServer = document.getElementById('selectedServer') as HTMLInputElement;
        this.initializeEventListeners();
    }

    private initializeEventListeners(): void {
        // Add click listeners to provider cards
        const providerCards = document.querySelectorAll<HTMLElement>('[data-provider]');

        providerCards.forEach((card) => {
            card.addEventListener('click', (event) => {
                const target = event.currentTarget as HTMLElement;
                const provider = target.getAttribute('data-provider');
                if (provider && this.isProviderAvailable(target)) {
                    this.selectProvider(provider);
                }
            });
        });

        // Add click listeners to server cards
        document.querySelectorAll<HTMLElement>('[data-server]').forEach(card => {
            card.addEventListener('click', (event) => {
                const target = event.currentTarget as HTMLElement;
                const serverId = target.getAttribute('data-server');
                if (this.isServerAvailable(target)) {
                    this.selectCustomServer(serverId || '');
                }
            });
        });
    }

    private isProviderAvailable(element: HTMLElement): boolean {
        return !element.classList.contains('disabled') &&
               !element.querySelector('.fa-lock');
    }

    private isServerAvailable(element: HTMLElement): boolean {
        return !element.classList.contains('disabled') &&
               element.classList.contains('cursor-pointer');
    }

    private selectProvider(provider: string): void {
        if (!this.selectedProvider) {
            return;
        }

        // Update hidden input
        this.selectedProvider.value = provider;

        // Update visual selection for provider cards
        document.querySelectorAll<HTMLElement>('[data-provider]').forEach(card => {
            this.updateCardSelection(card, false);
        });

        // Highlight selected card
        const selectedCard = document.querySelector<HTMLElement>(`[data-provider="${provider}"]`);
        if (selectedCard) {
            this.updateCardSelection(selectedCard, true);
        }

        // Show/hide server selection for Enterprise Dependency Track
        this.toggleServerSection(provider);
    }

    private selectCustomServer(serverId: string): void {
        if (!this.selectedServer) return;

        // Update hidden input
        this.selectedServer.value = serverId;

        // Update visual selection for server cards
        document.querySelectorAll<HTMLElement>('[data-server]').forEach(card => {
            this.updateCardSelection(card, false);
        });

        // Highlight selected card
        const selectedCard = document.querySelector<HTMLElement>(`[data-server="${serverId}"]`);
        if (selectedCard) {
            this.updateCardSelection(selectedCard, true);
        }
    }

    private updateCardSelection(card: HTMLElement, isSelected: boolean): void {
        if (isSelected) {
            card.classList.remove('border-secondary');
            card.classList.add('border-success', 'bg-success-subtle');

            // Update indicator icon
            const indicator = card.querySelector('.fa-circle, .fa-check-circle') as HTMLElement;
            if (indicator) {
                indicator.classList.remove('far', 'fa-circle', 'text-muted');
                indicator.classList.add('fas', 'fa-check-circle', 'text-success');
            }
        } else {
            card.classList.remove('border-success', 'bg-success-subtle');
            card.classList.add('border-secondary');

            // Update indicator icon (but only if it's not locked/disabled)
            const indicator = card.querySelector('.fa-check-circle, .fa-circle') as HTMLElement;
            if (indicator && !card.querySelector('.fa-lock')) {
                indicator.classList.remove('fas', 'fa-check-circle', 'text-success');
                indicator.classList.add('far', 'fa-circle', 'text-muted');
            }
        }
    }

    private toggleServerSection(provider: string): void {
        const serverSection = document.getElementById('server-selection-section') as HTMLElement;
        if (serverSection) {
            // More reliable way to check for enterprise plan
            const isEnterprise = this.isEnterprisePlan();

            if (provider === 'dependency_track' && isEnterprise) {
                serverSection.style.display = 'block';
            } else {
                serverSection.style.display = 'none';
            }
        }
    }

    private isEnterprisePlan(): boolean {
        // Check data attribute first (most reliable)
        const settingsContent = document.querySelector('.settings-content') as HTMLElement;
        if (settingsContent) {
            const billingPlan = settingsContent.getAttribute('data-billing-plan');
            if (billingPlan === 'enterprise') {
                return true;
            }
        }

        // Fallback: check for enterprise badge text
        const badges = document.querySelectorAll('.badge');
        for (const badge of badges) {
            if (badge.textContent?.includes('Enterprise')) {
                return true;
            }
        }

        return false;
    }
}

// Initialize when DOM is ready, but only on integrations pages
document.addEventListener('DOMContentLoaded', () => {
    // Only initialize on integrations pages
    if (document.getElementById('selectedProvider')) {
        new IntegrationsManager();
    }
});

/**
 * TypeScript functionality for Components Dashboard
 * Replaces Vue-based component interactions with vanilla TypeScript
 */

interface ComponentData {
    id: string;
    name: string;
    component_type: string;
    is_public: boolean;
}

/**
 * Initialize components dashboard functionality
 */
export function initializeComponentsDashboard(): void {
    // Initialize public status toggle functionality
    initializePublicStatusToggles();
    
    // Initialize any other component-specific interactions
    console.log('Components dashboard initialized');
}

/**
 * Initialize public status toggle buttons
 */
function initializePublicStatusToggles(): void {
    const toggleButtons = document.querySelectorAll('.toggle-public-btn');
    
    toggleButtons.forEach(button => {
        button.addEventListener('click', async (event) => {
            event.preventDefault();
            
            const btn = event.currentTarget as HTMLButtonElement;
            const componentId = btn.dataset.componentId;
            const isPublic = btn.dataset.isPublic === 'true';
            const componentName = btn.dataset.componentName;
            
            if (!componentId) return;
            
            // Show loading state
            const originalHTML = btn.innerHTML;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
            btn.disabled = true;
            
            try {
                const response = await fetch(`/toggle-public/component/${componentId}/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken(),
                    },
                    body: JSON.stringify({
                        is_public: !isPublic
                    })
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                const result = await response.json();
                
                // Update button state
                const newIsPublic = result.is_public;
                btn.dataset.isPublic = newIsPublic.toString();
                btn.title = newIsPublic ? 'Make Private' : 'Make Public';
                
                // Update button icon
                btn.innerHTML = newIsPublic 
                    ? '<i class="fas fa-lock"></i>'
                    : '<i class="fas fa-globe"></i>';
                
                // Update the status badge in the same row
                const row = btn.closest('tr');
                if (row) {
                    const statusCell = row.querySelector('[data-label="Public?"]');
                    if (statusCell) {
                        statusCell.innerHTML = newIsPublic
                            ? '<span class="badge bg-success-subtle text-success"><i class="fas fa-globe me-1"></i>Public</span>'
                            : '<span class="badge bg-secondary-subtle text-secondary"><i class="fas fa-lock me-1"></i>Private</span>';
                    }
                }
                
                // Show success message
                if (window.showSuccess) {
                    window.showSuccess(
                        `${componentName} is now ${newIsPublic ? 'public' : 'private'}`
                    );
                }
                
            } catch (error) {
                console.error('Error toggling public status:', error);
                
                // Show error message
                if (window.showError) {
                    window.showError('Failed to update component visibility');
                }
                
                // Restore original button content
                btn.innerHTML = originalHTML;
            } finally {
                btn.disabled = false;
            }
        });
    });
}

/**
 * Get CSRF token from cookie or meta tag
 */
function getCsrfToken(): string {
    // Try to get from cookie first
    const cookieValue = document.cookie
        .split('; ')
        .find(row => row.startsWith('csrftoken='))
        ?.split('=')[1];
    
    if (cookieValue) return cookieValue;
    
    // Fallback to meta tag
    const metaTag = document.querySelector('meta[name="csrf-token"]') as HTMLMetaElement;
    return metaTag?.content || '';
}

/**
 * Auto-initialize when DOM is ready
 */
document.addEventListener('DOMContentLoaded', () => {
    // Only initialize if we're on the components dashboard page
    if (document.querySelector('.components-table, #addComponentModal')) {
        initializeComponentsDashboard();
    }
});

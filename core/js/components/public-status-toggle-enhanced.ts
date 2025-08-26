/**
 * Enhanced TypeScript functionality for public status toggle
 * Provides better UX while still using server-side form submission
 */

import { NotificationManager } from '../utils/django-components';

class PublicStatusToggleEnhanced {
  private form: HTMLFormElement;
  private checkbox: HTMLInputElement;
  private statusText: HTMLElement;
  private publicUrlInfo: HTMLElement | null;

  constructor(form: HTMLFormElement) {
    this.form = form;
    this.checkbox = form.querySelector('.public-toggle-input') as HTMLInputElement;
    this.statusText = form.querySelector('.status-text') as HTMLElement;
    this.publicUrlInfo = form.querySelector('.public-url-info');

    this.initialize();
  }

  private initialize(): void {
    if (!this.checkbox || !this.statusText) return;

    // Remove the onchange attribute and handle it with JavaScript for better UX
    this.checkbox.removeAttribute('onchange');

    this.checkbox.addEventListener('change', (e) => {
      this.handleToggle(e);
    });
  }

  private async handleToggle(event: Event): Promise<void> {
    const checkbox = event.target as HTMLInputElement;
    const isPublic = checkbox.checked;

    // Show immediate feedback
    this.setLoadingState(true);
    this.updateStatusText(isPublic, true); // true = loading state

    try {
      // Create FormData from the form
      const formData = new FormData(this.form);

      // Ensure the checkbox value is included
      if (isPublic) {
        formData.set('is_public', 'true');
      } else {
        formData.delete('is_public'); // Unchecked checkboxes don't send values
      }

      // Submit the form via fetch for better UX
      const response = await fetch(this.form.action, {
        method: 'POST',
        body: formData,
        headers: {
          'X-Requested-With': 'XMLHttpRequest', // Mark as AJAX request
        }
      });

                  // Always try to parse JSON response first
      let responseData;
      try {
        responseData = await response.json();
      } catch {
        responseData = { detail: 'Invalid response format' };
      }

      if (response.ok) {
        // Update the UI immediately
        this.updateStatusText(isPublic, false);
        this.updatePublicUrlVisibility(isPublic);

        // Show success message
        const statusText = isPublic ? 'public' : 'private';
        NotificationManager.showSuccess(`Item is now ${statusText}`);

        // Add success animation
        this.showSuccessAnimation();
      } else {
        // Revert checkbox state to match actual database state
        checkbox.checked = !isPublic;
        this.updateStatusText(!isPublic, false);
        this.updatePublicUrlVisibility(!isPublic);

        // Show clean error message
        const errorMessage = responseData.detail || responseData.message || `HTTP ${response.status}: Error updating status`;
        NotificationManager.showError(errorMessage);
      }
    } catch (error) {
      // Revert checkbox state on error
      checkbox.checked = !isPublic;
      this.updateStatusText(!isPublic, false);

      console.error('Error toggling public status:', error);
      NotificationManager.showError(`Error updating status: ${error instanceof Error ? error.message : 'Network error'}`);
    } finally {
      this.setLoadingState(false);
    }
  }

  private updateStatusText(isPublic: boolean, isLoading: boolean = false): void {
    if (!this.statusText) return;

    if (isLoading) {
      this.statusText.innerHTML = `
        <i class="fas fa-spinner fa-spin text-primary me-2"></i>
        <span class="fw-medium">Updating...</span>
      `;
    } else if (isPublic) {
      this.statusText.innerHTML = `
        <i class="fas fa-globe text-success me-2"></i>
        <span class="fw-medium">Public</span>
      `;
    } else {
      this.statusText.innerHTML = `
        <i class="fas fa-lock text-secondary me-2"></i>
        <span class="fw-medium">Private</span>
      `;
    }
  }

  private updatePublicUrlVisibility(isPublic: boolean): void {
    if (!this.publicUrlInfo) return;

    if (isPublic) {
      this.publicUrlInfo.style.display = 'block';
    } else {
      this.publicUrlInfo.style.display = 'none';
    }
  }

  private setLoadingState(loading: boolean): void {
    if (this.checkbox) {
      this.checkbox.disabled = loading;
    }
  }

  private showSuccessAnimation(): void {
    // Add temporary success styling
    const originalStyle = this.form.style.cssText;

    this.form.style.transition = 'all 0.3s ease';
    this.form.style.backgroundColor = 'var(--bs-success-bg-subtle)';
    this.form.style.borderRadius = '0.5rem';
    this.form.style.padding = '0.25rem';
    this.form.style.border = '1px solid var(--bs-success-border-subtle)';

    setTimeout(() => {
      this.form.style.cssText = originalStyle;
    }, 2000);
  }
}

// Initialize all public status toggles when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  const toggleForms = document.querySelectorAll<HTMLFormElement>('.public-status-toggle');

  toggleForms.forEach(form => {
    console.log('Initializing enhanced PublicStatusToggle for server-side form');
    new PublicStatusToggleEnhanced(form);
  });
});

export { PublicStatusToggleEnhanced };

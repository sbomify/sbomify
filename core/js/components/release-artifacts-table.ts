/**
 * Release Artifacts Table functionality
 * Handles collapse toggle, remove artifact actions, and modal initialization
 */

import ReleaseArtifactsModal from './release-artifacts-modal';

interface ReleaseArtifactsTableOptions {
  releaseId: string;
}

class ReleaseArtifactsTable {
  private releaseId: string;

  constructor(options: ReleaseArtifactsTableOptions) {
    this.releaseId = options.releaseId;
    this.initializeEventListeners();
    this.initializeModal();
  }

  private initializeEventListeners(): void {
    // Collapse toggle functionality
    this.initializeCollapseButtons();

    // Remove artifact button handlers
    this.initializeRemoveButtons();
  }

  private initializeCollapseButtons(): void {
    const collapseButtons = document.querySelectorAll('[data-bs-toggle="collapse"]');
    collapseButtons.forEach(button => {
      const target = button.getAttribute('data-bs-target');
      const collapseElement = target ? document.querySelector(target) : null;

      if (collapseElement) {
        collapseElement.addEventListener('shown.bs.collapse', () => {
          const icon = button.querySelector('i');
          if (icon) {
            icon.className = 'fas fa-chevron-up transition-transform';
          }
        });

        collapseElement.addEventListener('hidden.bs.collapse', () => {
          const icon = button.querySelector('i');
          if (icon) {
            icon.className = 'fas fa-chevron-down transition-transform';
          }
        });
      }
    });
  }

  private initializeRemoveButtons(): void {
    const removeButtons = document.querySelectorAll('.remove-artifact-btn');
    removeButtons.forEach(button => {
      button.addEventListener('click', (event) => {
        const target = event.currentTarget as HTMLElement;
        const artifactId = target.dataset.artifactId;
        const artifactName = target.dataset.artifactName;

        if (artifactId && artifactName) {
          this.handleRemoveArtifact(artifactId, artifactName);
        }
      });
    });
  }

  private initializeModal(): void {
    // Initialize the Add Artifact modal if it exists
    const modalElement = document.getElementById('addArtifactModal');
    if (modalElement) {
      try {
        new ReleaseArtifactsModal({
          modalId: 'addArtifactModal',
          releaseId: this.releaseId,
          productId: '', // Will be determined from context
          apiBaseUrl: ''  // Will use relative URLs
        });
        console.log('Artifacts modal initialized successfully');
      } catch (error) {
        console.error('Failed to initialize artifacts modal:', error);
      }
    }
  }

  private async handleRemoveArtifact(artifactId: string, artifactName: string): Promise<void> {
    const confirmed = confirm(`Are you sure you want to remove "${artifactName}" from this release?`);

    if (!confirmed) {
      return;
    }

    try {
      const response = await fetch(`/api/v1/releases/${this.releaseId}/artifacts/${artifactId}`, {
        method: 'DELETE',
        headers: {
          'X-CSRFToken': this.getCSRFToken(),
          'Content-Type': 'application/json'
        }
      });

      if (response.ok) {
        // Show success message and reload
        this.showSuccess(`Successfully removed ${artifactName} from the release`);
        window.location.reload();
      } else {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to remove artifact');
      }
    } catch (error) {
      console.error('Error removing artifact:', error);
      this.showError(`Error removing artifact: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  }

  private getCSRFToken(): string {
    const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]') as HTMLInputElement;
    return csrfInput?.value || '';
  }

  private showSuccess(message: string): void {
    // You can integrate with your existing alert system here
    alert(message);
  }

  private showError(message: string): void {
    // You can integrate with your existing alert system here
    alert(message);
  }
}

// Global initialization function
window.initializeReleaseArtifactsTable = (options: ReleaseArtifactsTableOptions) => {
  return new ReleaseArtifactsTable(options);
};

// Auto-initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  // Look for release artifacts tables and auto-initialize them
  const tables = document.querySelectorAll('[data-release-id]');
  tables.forEach(table => {
    const releaseId = table.getAttribute('data-release-id');
    if (releaseId) {
      new ReleaseArtifactsTable({ releaseId });
    }
  });
});

// Type declaration for global usage
declare global {
  interface Window {
    initializeReleaseArtifactsTable: (options: ReleaseArtifactsTableOptions) => ReleaseArtifactsTable;
  }
}

export default ReleaseArtifactsTable;


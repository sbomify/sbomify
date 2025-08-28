/**
 * TypeScript functionality for Django danger zone component
 * Handles delete confirmation and API calls
 */

import { NotificationManager, ApiClient, DomUtils } from '../utils/django-components';

interface DangerZoneConfig {
  itemType: string;
  itemId: string;
  itemName: string;
  deleteEndpoint: string;
  redirectUrl: string;
}

export class DangerZoneManager {
  private config: DangerZoneConfig;

  constructor(config: DangerZoneConfig) {
    this.config = config;
    this.initialize();
  }

  private initialize(): void {
    console.log('Initializing DangerZoneManager with config:', this.config);
    this.attachDeleteButtonListener();
    this.attachCollapseToggleListener();
  }

  private attachDeleteButtonListener(): void {
    const deleteButtons = DomUtils.getElements<HTMLButtonElement>('.danger-delete-btn');
    console.log('Found danger delete buttons:', deleteButtons.length);

    deleteButtons.forEach(deleteBtn => {
      deleteBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        console.log('Danger delete button clicked:', deleteBtn.dataset);
        await this.handleDelete(deleteBtn);
      });
    });
  }

  private async handleDelete(button: HTMLButtonElement): Promise<void> {
    const itemName = button.dataset.itemName || `this ${this.config.itemType}`;
    const itemType = button.dataset.itemType || this.config.itemType;

    // Use the new Bootstrap 5 confirmation system
    const confirmed = await NotificationManager.showConfirmation(
      `Are you sure you want to delete "${itemName}"? This action cannot be undone and will permanently remove the ${itemType} and all associated data.`,
      'Delete ' + itemType.charAt(0).toUpperCase() + itemType.slice(1),
      'Yes, delete it!',
      'Cancel'
    );

    if (!confirmed) return;

    try {
      // Replace {id} placeholder in endpoint with actual ID
      const deleteUrl = this.config.deleteEndpoint.replace('{id}', this.config.itemId);

      await ApiClient.delete(deleteUrl);

      NotificationManager.showSuccess(`${itemType.charAt(0).toUpperCase() + itemType.slice(1)} deleted successfully!`);

      // Redirect after successful deletion
      if (this.config.redirectUrl) {
        setTimeout(() => {
          window.location.href = this.config.redirectUrl;
        }, 1500);
      } else {
        window.location.reload();
      }
    } catch (error) {
      console.error(`Error deleting ${itemType}:`, error);
      NotificationManager.showError(`Error deleting ${itemType}: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  }

  private attachCollapseToggleListener(): void {
    // Fix collapse button icon direction
    const collapseButtons = DomUtils.getElements<HTMLButtonElement>('[data-bs-toggle="collapse"]');

    collapseButtons.forEach(button => {
      const target = button.getAttribute('data-bs-target');
      if (!target) return;
      const collapseElement = document.querySelector(target);

      if (collapseElement) {
        collapseElement.addEventListener('shown.bs.collapse', () => {
          const icon = button.querySelector('i');
          if (icon) icon.className = 'fas fa-chevron-down transition-transform';
        });

        collapseElement.addEventListener('hidden.bs.collapse', () => {
          const icon = button.querySelector('i');
          if (icon) icon.className = 'fas fa-chevron-up transition-transform';
        });
      }
    });
  }
}

// Initialize danger zone when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  // Look for danger zone configuration
  const dangerZoneElement = document.querySelector('[data-danger-zone-config]') as HTMLElement;

  if (dangerZoneElement && dangerZoneElement.dataset.dangerZoneConfig) {
    try {
      const config: DangerZoneConfig = JSON.parse(dangerZoneElement.dataset.dangerZoneConfig);
      console.log('Initializing DangerZoneManager with config:', config);
      new DangerZoneManager(config);
    } catch (error) {
      console.error('Error parsing danger zone config:', error);
    }
  }
});

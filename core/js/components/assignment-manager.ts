/**
 * Generic Assignment Manager for parent-child relationships
 * Handles assigning/removing projects to products, components to projects, etc.
 */

import { NotificationManager, ApiClient, DomUtils } from '../utils/django-components';

interface AssignmentConfig {
  parentType: string;  // 'product', 'project', 'release'
  parentId: string;
  childType: string;   // 'project', 'component', 'artifact'
  hasCrudPermissions: boolean;
}

class AssignmentManager {
  private config: AssignmentConfig;

  constructor(config: AssignmentConfig) {
    this.config = config;
    this.initialize();
  }

  private initialize(): void {
    if (!this.config.hasCrudPermissions) return;

    this.attachEventListeners();
    this.attachSearchListeners();
  }

  private attachEventListeners(): void {
    // Assign button listeners
    const assignButtons = DomUtils.getElements<HTMLButtonElement>('.assign-item-btn');
    console.log('Found assign buttons:', assignButtons.length);
    assignButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        console.log('Assign button clicked:', btn.dataset);
        this.handleAssign(btn);
      });
    });

    // Remove button listeners
    const removeButtons = DomUtils.getElements<HTMLButtonElement>('.remove-item-btn');
    console.log('Found remove buttons:', removeButtons.length);
    removeButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        console.log('Remove button clicked:', btn.dataset);
        this.handleRemove(btn);
      });
    });
  }

  private attachSearchListeners(): void {
    // Search functionality for assigned items
    const assignedSearch = DomUtils.getElement<HTMLInputElement>('assignedSearch');
    if (assignedSearch) {
      assignedSearch.addEventListener('input', () => {
        this.filterItems(assignedSearch.value, '.assigned-item');
      });
    }

    // Search functionality for available items
    const availableSearch = DomUtils.getElement<HTMLInputElement>('availableSearch');
    if (availableSearch) {
      availableSearch.addEventListener('input', () => {
        this.filterItems(availableSearch.value, '.available-item');
      });
    }
  }

  private filterItems(searchTerm: string, selector: string): void {
    const items = DomUtils.getElements<HTMLElement>(selector);
    const lowerSearchTerm = searchTerm.toLowerCase();

    items.forEach(item => {
      const itemName = item.dataset.itemName || '';
      if (itemName.includes(lowerSearchTerm)) {
        item.style.display = 'flex';
      } else {
        item.style.display = 'none';
      }
    });
  }

  private async handleAssign(button: HTMLButtonElement): Promise<void> {
    const itemId = button.dataset.itemId;
    const itemName = button.dataset.itemName;

    if (!itemId || !itemName) return;

    try {
      button.disabled = true;

      // Get currently assigned items
      const assignedItems = Array.from(DomUtils.getElements('.assigned-item')).map(el => el.dataset.itemId);
      const newAssignedIds = [...assignedItems, itemId];

      // Make API call to update assignments
      await this.updateAssignments(newAssignedIds);

      NotificationManager.showSuccess(`${itemName} assigned successfully`);

      // Reload page to show updated assignments
      window.location.reload();

    } catch (error) {
      console.error('Error assigning item:', error);
      NotificationManager.showError(`Error assigning ${itemName}: ${error instanceof Error ? error.message : 'Unknown error'}`);
      button.disabled = false;
    }
  }

  private async handleRemove(button: HTMLButtonElement): Promise<void> {
    const itemId = button.dataset.itemId;
    const itemName = button.dataset.itemName;

    if (!itemId || !itemName) return;

    const confirmed = await NotificationManager.showConfirmation(
      `Are you sure you want to remove "${itemName}" from this ${this.config.parentType}?`
    );

    if (!confirmed) return;

    try {
      button.disabled = true;

      // Get currently assigned items and remove this one
      const assignedItems = Array.from(DomUtils.getElements('.assigned-item'))
        .map(el => el.dataset.itemId)
        .filter(id => id !== itemId);

      // Make API call to update assignments
      await this.updateAssignments(assignedItems);

      NotificationManager.showSuccess(`${itemName} removed successfully`);

      // Reload page to show updated assignments
      window.location.reload();

    } catch (error) {
      console.error('Error removing item:', error);
      NotificationManager.showError(`Error removing ${itemName}: ${error instanceof Error ? error.message : 'Unknown error'}`);
      button.disabled = false;
    }
  }

  private async updateAssignments(assignedIds: (string | undefined)[]): Promise<void> {
    const validIds = assignedIds.filter(id => id) as string[];

    // Determine API endpoint and field name based on parent/child types
    const endpoint = `/api/v1/${this.config.parentType}s/${this.config.parentId}`;
    const fieldName = `${this.config.childType}_ids`;

    const patchData = {
      [fieldName]: validIds
    };

    await ApiClient.patch(endpoint, patchData);
  }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  const assignmentContainer = document.querySelector('[data-assignment-manager]') as HTMLElement;

  if (assignmentContainer) {
    const parentType = assignmentContainer.dataset.parentType;
    const parentId = assignmentContainer.dataset.parentId;
    const childType = assignmentContainer.dataset.childType;
    const hasCrudPermissions = assignmentContainer.dataset.hasCrudPermissions === 'true';

    if (parentType && parentId && childType) {
      console.log('Initializing AssignmentManager:', { parentType, parentId, childType, hasCrudPermissions });
      new AssignmentManager({
        parentType,
        parentId,
        childType,
        hasCrudPermissions
      });
    }
  }
});

export { AssignmentManager };

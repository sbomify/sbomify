/**
 * TypeScript for Release Artifacts Modal functionality
 * Handles adding artifacts to releases with Django API integration
 */

interface Artifact {
  id: string;
  artifact_type: 'sbom' | 'document';
  name: string;
  version?: string;
  format?: string;
  format_version?: string;
  document_type?: string;
  created_at: string;
  component: {
    id: string;
    name: string;
    component_type: string;
  };
}

interface ArtifactModalOptions {
  releaseId: string;
  productId: string;
  modalId: string;
  apiBaseUrl: string;
}

class ReleaseArtifactsModal {
  private releaseId: string;

  private modalElement: HTMLElement;
  private apiBaseUrl: string;
  private availableArtifacts: Artifact[] = [];
  private selectedArtifacts: Set<string> = new Set();
  private isLoading = false;
  private currentPage = 1;
  private itemsPerPage = 25;
  private searchQuery = '';
  private filterType = '';
  private filterComponent = '';

  constructor(options: ArtifactModalOptions) {
    this.releaseId = options.releaseId;
    // productId stored but not used directly in this class
    this.apiBaseUrl = options.apiBaseUrl;

    const modalElement = document.getElementById(options.modalId);
    if (!modalElement) {
      throw new Error(`Modal element with ID ${options.modalId} not found`);
    }
    this.modalElement = modalElement;

    this.initializeEventListeners();
  }

  private initializeEventListeners(): void {
    // Modal show event
    this.modalElement.addEventListener('show.bs.modal', () => {
      this.loadAvailableArtifacts();
      this.resetFilters();
    });

    // Search input
    const searchInput = this.modalElement.querySelector('#artifactSearch') as HTMLInputElement;
    if (searchInput) {
      searchInput.addEventListener('input', this.debounce(() => {
        this.searchQuery = searchInput.value;
        this.currentPage = 1;
        this.renderArtifacts();
      }, 300));
    }

    // Filter controls
    const typeFilter = this.modalElement.querySelector('#artifactTypeFilter') as HTMLSelectElement;
    if (typeFilter) {
      typeFilter.addEventListener('change', () => {
        this.filterType = typeFilter.value;
        this.currentPage = 1;
        this.renderArtifacts();
      });
    }

    const componentFilter = this.modalElement.querySelector('#artifactComponentFilter') as HTMLSelectElement;
    if (componentFilter) {
      componentFilter.addEventListener('change', () => {
        this.filterComponent = componentFilter.value;
        this.currentPage = 1;
        this.renderArtifacts();
      });
    }

    // Select all checkbox
    const selectAllCheckbox = this.modalElement.querySelector('#selectAllArtifacts') as HTMLInputElement;
    if (selectAllCheckbox) {
      selectAllCheckbox.addEventListener('change', () => {
        this.toggleSelectAll(selectAllCheckbox.checked);
      });
    }

    // Clear selection button
    const clearButton = this.modalElement.querySelector('#clearSelection');
    if (clearButton) {
      clearButton.addEventListener('click', () => {
        this.clearSelection();
      });
    }

    // Add artifacts button
    const addButton = this.modalElement.querySelector('#addSelectedArtifacts');
    if (addButton) {
      addButton.addEventListener('click', () => {
        this.addSelectedArtifacts();
      });
    }
  }

  private async loadAvailableArtifacts(): Promise<void> {
    if (this.isLoading) return;

    this.isLoading = true;
    this.showLoadingState();

    try {
      const response = await fetch(`${this.apiBaseUrl}/api/v1/releases/${this.releaseId}/artifacts?mode=available`);

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      this.availableArtifacts = Array.isArray(data) ? data : data.items || [];

      this.renderArtifacts();
      this.updateComponentFilter();

    } catch (error) {
      console.error('Error loading available artifacts:', error);
      this.showErrorState('Failed to load available artifacts. Please try again.');
    } finally {
      this.isLoading = false;
    }
  }

  private getFilteredArtifacts(): Artifact[] {
    let filtered = this.availableArtifacts;

    // Apply search filter
    if (this.searchQuery.trim()) {
      const query = this.searchQuery.toLowerCase().trim();
      filtered = filtered.filter(artifact =>
        artifact.name.toLowerCase().includes(query) ||
        artifact.component.name.toLowerCase().includes(query) ||
        this.getArtifactFormat(artifact).toLowerCase().includes(query) ||
        (artifact.version && artifact.version.toLowerCase().includes(query))
      );
    }

    // Apply type filter
    if (this.filterType) {
      filtered = filtered.filter(artifact => artifact.artifact_type === this.filterType);
    }

    // Apply component filter
    if (this.filterComponent) {
      filtered = filtered.filter(artifact => artifact.component.name === this.filterComponent);
    }

    return filtered;
  }

  private getPaginatedArtifacts(): Artifact[] {
    const filtered = this.getFilteredArtifacts();
    const start = (this.currentPage - 1) * this.itemsPerPage;
    const end = start + this.itemsPerPage;
    return filtered.slice(start, end);
  }

  private renderArtifacts(): void {
    const container = this.modalElement.querySelector('#artifactsTableContainer');
    if (!container) return;

    const filteredArtifacts = this.getFilteredArtifacts();
    const paginatedArtifacts = this.getPaginatedArtifacts();

    if (filteredArtifacts.length === 0) {
      container.innerHTML = this.getEmptyStateHTML();
      return;
    }

    const tableHTML = `
      <div class="mb-3 d-flex justify-content-between align-items-center">
        <small class="text-muted">
          Showing ${paginatedArtifacts.length} of ${filteredArtifacts.length} artifacts
          ${this.selectedArtifacts.size > 0 ? `(${this.selectedArtifacts.size} selected)` : ''}
        </small>
        <div class="btn-group btn-group-sm">
          <button type="button" class="btn btn-outline-primary" id="selectAllVisible"
                  ${paginatedArtifacts.length === 0 ? 'disabled' : ''}>
            Select All Visible
          </button>
          <button type="button" class="btn btn-outline-secondary" id="clearSelection"
                  ${this.selectedArtifacts.size === 0 ? 'disabled' : ''}>
            Clear Selection
          </button>
        </div>
      </div>
      <div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
        <table class="table table-hover table-sm">
          <thead class="table-light sticky-top">
            <tr>
              <th style="width: 40px;">
                <input type="checkbox" class="form-check-input" id="selectAllArtifacts">
              </th>
              <th style="width: 40px;">Type</th>
              <th>Name</th>
              <th>Component</th>
              <th>Format/Type</th>
              <th>Version</th>
              <th style="width: 100px;">Created</th>
            </tr>
          </thead>
          <tbody>
            ${paginatedArtifacts.map(artifact => this.renderArtifactRow(artifact)).join('')}
          </tbody>
        </table>
      </div>
      ${this.renderPagination(filteredArtifacts.length)}
    `;

    container.innerHTML = tableHTML;
    this.attachRowEventListeners();
    this.updateSelectAllCheckbox();
    this.updateAddButton();
  }

  private renderArtifactRow(artifact: Artifact): string {
    const isSelected = this.selectedArtifacts.has(this.getArtifactKey(artifact));
    const iconClass = artifact.artifact_type === 'sbom' ? 'fas fa-file-code sbom-icon' : 'fas fa-file-alt document-icon';
    const format = this.getArtifactFormat(artifact);
    const version = artifact.version || '—';
    const createdDate = new Date(artifact.created_at).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    });

    return `
      <tr class="artifact-table-row ${isSelected ? 'table-active' : ''}"
          data-artifact-key="${this.getArtifactKey(artifact)}">
        <td>
          <input type="checkbox" class="form-check-input artifact-checkbox"
                 ${isSelected ? 'checked' : ''}>
        </td>
        <td>
          <span class="artifact-type-icon-sm ${artifact.artifact_type}-icon">
            <i class="${iconClass} fa-sm"></i>
          </span>
        </td>
        <td>
          <div class="artifact-name-cell">
            <div class="fw-medium">${this.escapeHtml(artifact.name)}</div>
            ${artifact.version ? `<div class="text-muted small">${this.escapeHtml(artifact.version)}</div>` : ''}
          </div>
        </td>
        <td>
          <span class="component-link">${this.escapeHtml(artifact.component.name)}</span>
        </td>
        <td>
          <span class="format-text">${this.escapeHtml(format)}</span>
        </td>
        <td>
          <span class="version-text">${this.escapeHtml(version)}</span>
        </td>
        <td>
          <small class="text-muted">${createdDate}</small>
        </td>
      </tr>
    `;
  }

  private attachRowEventListeners(): void {
    const rows = this.modalElement.querySelectorAll('.artifact-table-row');
    rows.forEach(row => {
      const artifactKey = row.getAttribute('data-artifact-key');
      if (!artifactKey) return;

      row.addEventListener('click', (e) => {
        if ((e.target as HTMLInputElement).type !== 'checkbox') {
          this.toggleArtifactSelection(artifactKey);
        }
      });

      const checkbox = row.querySelector('.artifact-checkbox') as HTMLInputElement;
      if (checkbox) {
        checkbox.addEventListener('change', () => {
          this.toggleArtifactSelection(artifactKey);
        });
      }
    });

    // Select all visible button
    const selectAllVisibleBtn = this.modalElement.querySelector('#selectAllVisible');
    if (selectAllVisibleBtn) {
      selectAllVisibleBtn.addEventListener('click', () => {
        this.selectAllVisible();
      });
    }
  }

  private toggleArtifactSelection(artifactKey: string): void {
    if (this.selectedArtifacts.has(artifactKey)) {
      this.selectedArtifacts.delete(artifactKey);
    } else {
      this.selectedArtifacts.add(artifactKey);
    }
    this.updateRowSelection(artifactKey);
    this.updateSelectAllCheckbox();
    this.updateAddButton();
  }

  private updateRowSelection(artifactKey: string): void {
    const row = this.modalElement.querySelector(`[data-artifact-key="${artifactKey}"]`);
    if (!row) return;

    const checkbox = row.querySelector('.artifact-checkbox') as HTMLInputElement;
    const isSelected = this.selectedArtifacts.has(artifactKey);

    if (checkbox) {
      checkbox.checked = isSelected;
    }

    row.classList.toggle('table-active', isSelected);
  }

  private selectAllVisible(): void {
    const visibleRows = this.modalElement.querySelectorAll('.artifact-table-row');
    visibleRows.forEach(row => {
      const artifactKey = row.getAttribute('data-artifact-key');
      if (artifactKey) {
        this.selectedArtifacts.add(artifactKey);
        this.updateRowSelection(artifactKey);
      }
    });
    this.updateSelectAllCheckbox();
    this.updateAddButton();
  }

  private toggleSelectAll(selectAll: boolean): void {
    if (selectAll) {
      this.selectAllVisible();
    } else {
      this.clearVisibleSelection();
    }
  }

  private clearSelection(): void {
    this.selectedArtifacts.clear();
    this.renderArtifacts();
  }

  private clearVisibleSelection(): void {
    const visibleRows = this.modalElement.querySelectorAll('.artifact-table-row');
    visibleRows.forEach(row => {
      const artifactKey = row.getAttribute('data-artifact-key');
      if (artifactKey) {
        this.selectedArtifacts.delete(artifactKey);
        this.updateRowSelection(artifactKey);
      }
    });
    this.updateSelectAllCheckbox();
    this.updateAddButton();
  }

  private updateSelectAllCheckbox(): void {
    const selectAllCheckbox = this.modalElement.querySelector('#selectAllArtifacts') as HTMLInputElement;
    if (!selectAllCheckbox) return;

    const visibleRows = this.modalElement.querySelectorAll('.artifact-table-row');
    const visibleKeys = Array.from(visibleRows).map(row => row.getAttribute('data-artifact-key')).filter(Boolean);
    const selectedVisibleCount = visibleKeys.filter(key => this.selectedArtifacts.has(key!)).length;

    if (selectedVisibleCount === 0) {
      selectAllCheckbox.checked = false;
      selectAllCheckbox.indeterminate = false;
    } else if (selectedVisibleCount === visibleKeys.length) {
      selectAllCheckbox.checked = true;
      selectAllCheckbox.indeterminate = false;
    } else {
      selectAllCheckbox.checked = false;
      selectAllCheckbox.indeterminate = true;
    }
  }

  private updateAddButton(): void {
    const addButton = this.modalElement.querySelector('#addSelectedArtifacts') as HTMLButtonElement;
    if (!addButton) return;

    const count = this.selectedArtifacts.size;
    addButton.disabled = count === 0;
    addButton.textContent = count > 0 ? `Add ${count} Artifact${count === 1 ? '' : 's'}` : 'Add Artifacts';
  }

  private async addSelectedArtifacts(): Promise<void> {
    if (this.selectedArtifacts.size === 0) return;

    const addButton = this.modalElement.querySelector('#addSelectedArtifacts') as HTMLButtonElement;
    if (addButton) {
      addButton.disabled = true;
      addButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Adding...';
    }

    try {
      const selectedArtifactData = Array.from(this.selectedArtifacts).map(key => {
        const [type, id] = key.split('-');
        return this.availableArtifacts.find(a => a.artifact_type === type && a.id === id);
      }).filter(Boolean) as Artifact[];

      const results = [];
      for (const artifact of selectedArtifactData) {
        try {
          const payload: Record<string, string> = {};
          if (artifact.artifact_type === 'sbom') {
            payload.sbom_id = artifact.id;
          } else {
            payload.document_id = artifact.id;
          }

          const response = await fetch(`${this.apiBaseUrl}/api/v1/releases/${this.releaseId}/artifacts`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': this.getCSRFToken()
            },
            body: JSON.stringify(payload)
          });

          if (response.ok) {
            results.push({ success: true, artifact });
          } else {
            const errorData = await response.json();
            results.push({ success: false, artifact, error: errorData.detail || 'Unknown error' });
          }
        } catch {
          results.push({ success: false, artifact, error: 'Network error' });
        }
      }

      const successful = results.filter(r => r.success);
      const failed = results.filter(r => !r.success);

      if (successful.length > 0) {
        this.showSuccess(`Successfully added ${successful.length} artifact${successful.length === 1 ? '' : 's'} to the release`);
      }

      if (failed.length > 0) {
        const errorMessages = failed.map(f => `${f.artifact.name}: ${f.error}`);
        this.showError(`Failed to add ${failed.length} artifact${failed.length === 1 ? '' : 's'}:\n${errorMessages.join('\n')}`);
      }

      // Close modal and reload page
      this.closeModal();
      window.location.reload();

    } catch (error) {
      console.error('Error adding artifacts:', error);
      this.showError('Failed to add artifacts');
    } finally {
      if (addButton) {
        addButton.disabled = false;
        addButton.textContent = 'Add Artifacts';
      }
    }
  }

  private getArtifactKey(artifact: Artifact): string {
    return `${artifact.artifact_type}-${artifact.id}`;
  }

  private getArtifactFormat(artifact: Artifact): string {
    if (artifact.artifact_type === 'sbom' && artifact.format && artifact.format_version) {
      const formatDisplay = artifact.format === 'cyclonedx' ? 'CycloneDX' : artifact.format.toUpperCase();
      return `${formatDisplay} ${artifact.format_version}`;
    }
    if (artifact.artifact_type === 'document' && artifact.document_type) {
      return artifact.document_type.charAt(0).toUpperCase() + artifact.document_type.slice(1);
    }
    return 'Unknown';
  }

  private renderPagination(totalItems: number): string {
    const totalPages = Math.ceil(totalItems / this.itemsPerPage);
    if (totalPages <= 1) return '';

    const pages = [];
    for (let i = 1; i <= totalPages; i++) {
      if (i === 1 || i === totalPages || Math.abs(i - this.currentPage) <= 2) {
        pages.push(i);
      } else if (pages[pages.length - 1] !== '...') {
        pages.push('...');
      }
    }

    return `
      <nav aria-label="Artifacts pagination">
        <ul class="pagination pagination-sm justify-content-center mt-3">
          <li class="page-item ${this.currentPage === 1 ? 'disabled' : ''}">
            <button class="page-link" data-page="${this.currentPage - 1}" ${this.currentPage === 1 ? 'disabled' : ''}>Previous</button>
          </li>
          ${pages.map(page => `
            <li class="page-item ${page === this.currentPage ? 'active' : ''} ${page === '...' ? 'disabled' : ''}">
              <button class="page-link" ${page === '...' ? 'disabled' : `data-page="${page}"`}>
                ${page}
              </button>
            </li>
          `).join('')}
          <li class="page-item ${this.currentPage === totalPages ? 'disabled' : ''}">
            <button class="page-link" data-page="${this.currentPage + 1}" ${this.currentPage === totalPages ? 'disabled' : ''}>Next</button>
          </li>
        </ul>
      </nav>
    `;
  }

  private updateComponentFilter(): void {
    const componentFilter = this.modalElement.querySelector('#artifactComponentFilter') as HTMLSelectElement;
    if (!componentFilter) return;

    const components = [...new Set(this.availableArtifacts.map(a => a.component.name))].sort();
    const currentValue = componentFilter.value;

    componentFilter.innerHTML = `
      <option value="">All Components</option>
      ${components.map(component => `
        <option value="${this.escapeHtml(component)}" ${component === currentValue ? 'selected' : ''}>
          ${this.escapeHtml(component)}
        </option>
      `).join('')}
    `;
  }

  private showLoadingState(): void {
    const container = this.modalElement.querySelector('#artifactsTableContainer');
    if (container) {
      container.innerHTML = `
        <div class="text-center py-4">
          <div class="spinner-border spinner-border-sm text-primary" role="status">
            <span class="visually-hidden">Loading...</span>
          </div>
          <div class="ms-2">Loading artifacts...</div>
        </div>
      `;
    }
  }

  private showErrorState(message: string): void {
    const container = this.modalElement.querySelector('#artifactsTableContainer');
    if (container) {
      container.innerHTML = `
        <div class="text-center py-4 text-danger">
          <i class="fas fa-exclamation-triangle fa-2x mb-2"></i>
          <div>${this.escapeHtml(message)}</div>
          <button class="btn btn-outline-primary btn-sm mt-2" onclick="location.reload()">
            Retry
          </button>
        </div>
      `;
    }
  }

  private getEmptyStateHTML(): string {
    return `
      <div class="text-center py-4 text-muted">
        <i class="fas fa-search fa-2x mb-2 opacity-50"></i>
        <div>No artifacts match your search criteria</div>
        <button class="btn btn-link btn-sm mt-2" onclick="this.closest('.modal').querySelector('#artifactSearch').value=''; this.closest('.modal').querySelector('#artifactTypeFilter').value=''; this.closest('.modal').querySelector('#artifactComponentFilter').value='';">
          Clear filters
        </button>
      </div>
    `;
  }

  private resetFilters(): void {
    this.searchQuery = '';
    this.filterType = '';
    this.filterComponent = '';
    this.currentPage = 1;
    this.selectedArtifacts.clear();

    const searchInput = this.modalElement.querySelector('#artifactSearch') as HTMLInputElement;
    if (searchInput) searchInput.value = '';

    const typeFilter = this.modalElement.querySelector('#artifactTypeFilter') as HTMLSelectElement;
    if (typeFilter) typeFilter.value = '';

    const componentFilter = this.modalElement.querySelector('#artifactComponentFilter') as HTMLSelectElement;
    if (componentFilter) componentFilter.value = '';
  }

  private closeModal(): void {
    const modal = window.bootstrap?.Modal.getInstance(this.modalElement);
    if (modal) {
      modal.hide();
    }
  }

  private getCSRFToken(): string {
    const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]') as HTMLInputElement;
    return csrfInput?.value || '';
  }

  private debounce<T extends (...args: unknown[]) => void>(func: T, wait: number): T {
    let timeout: NodeJS.Timeout;
    return ((...args: Parameters<T>) => {
      clearTimeout(timeout);
      timeout = setTimeout(() => func(...args), wait);
    }) as T;
  }

  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
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
window.initializeReleaseArtifactsModal = (options: ArtifactModalOptions) => {
  return new ReleaseArtifactsModal(options);
};

// Type declaration for global usage
declare global {
  interface Window {
    initializeReleaseArtifactsModal: (options: ArtifactModalOptions) => ReleaseArtifactsModal;
  }
}

export default ReleaseArtifactsModal;


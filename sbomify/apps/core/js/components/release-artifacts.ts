import Alpine from 'alpinejs';
import $axios, { confirmDelete } from '../utils';
import { showError, showSuccess } from '../alerts';

interface SBOMData {
    id: string;
    name: string;
    format?: string;
    format_version?: string;
    version?: string;
    created_at?: string;
    component?: { id: string; name: string };
}

interface DocumentData {
    id: string;
    name: string;
    document_type?: string;
    version?: string;
    created_at?: string;
    component?: { id: string; name: string };
}

interface Artifact {
    id: string;
    name?: string;
    type?: string;
    artifact_type?: string;
    artifact_name?: string;
    sbom_id?: string;
    document_id?: string;
    sbom_format?: string;
    sbom_format_version?: string;
    sbom_version?: string;
    document_type?: string;
    document_version?: string;
    component_id?: string;
    component_name?: string;
    file_size?: number;
    created_at?: string;
    download_url?: string;
    sbom?: SBOMData | null;
    document?: DocumentData | null;
}

interface AvailableArtifact {
    id: string;
    artifact_type: 'sbom' | 'document';
    name: string;
    version?: string;
    format?: string;
    format_version?: string;
    document_type?: string;
    created_at: string;
    component?: {
        id: string;
        name: string;
        component_type?: string;
    };
}

interface ReleaseArtifactsParams {
    releaseId: string;
    productId: string;
    initialArtifacts?: Artifact[];
    canEdit?: boolean;
    isLatest?: boolean;
}

export function registerReleaseArtifacts() {
    Alpine.data('releaseArtifacts', ({
        releaseId,
        productId,
        initialArtifacts = [],
        canEdit = true,
        isLatest = false
    }: ReleaseArtifactsParams) => {
        return {
            artifacts: initialArtifacts as Artifact[],
            availableArtifacts: [] as AvailableArtifact[],
            selectedArtifacts: new Set<string>(),
            isLoading: false,
            isLoadingAvailable: false,
            isSubmitting: false,
            showAddModal: false,
            releaseId,
            productId,
            canEdit,
            isLatest,

            // Main table filters
            search: '',
            typeFilter: '',
            componentFilter: '',
            currentPage: 1,
            pageSize: 25,

            // Modal filters
            availableSearch: '',
            availableTypeFilter: '',
            availableComponentFilter: '',

            init() {
                if (initialArtifacts.length === 0) {
                    this.loadArtifacts();
                }
            },

            async loadArtifacts() {
                this.isLoading = true;
                try {
                    const response = await $axios.get(
                        `/api/v1/releases/${this.releaseId}/artifacts?mode=existing`
                    );
                    const artifactsData = Array.isArray(response.data) ? response.data : response.data.items || [];
                    this.artifacts = artifactsData;
                } catch (error) {
                    console.error('Failed to load artifacts:', error);
                    showError('Failed to load artifacts');
                } finally {
                    this.isLoading = false;
                }
            },

            async loadAvailableArtifacts() {
                this.isLoadingAvailable = true;
                try {
                    const response = await $axios.get(`/api/v1/releases/${this.releaseId}/artifacts?mode=available`);
                    const data = Array.isArray(response.data) ? response.data : response.data.items || [];
                    this.availableArtifacts = data;
                } catch (error) {
                    console.error('Failed to load available artifacts:', error);
                    showError('Failed to load available artifacts');
                } finally {
                    this.isLoadingAvailable = false;
                }
            },

            // Computed-like getters for main table
            get uniqueComponents(): string[] {
                const components = new Set<string>();
                this.artifacts.forEach((a: Artifact) => {
                    const name = this.getArtifactComponent(a);
                    if (name && name !== '-') components.add(name);
                });
                return Array.from(components).sort();
            },

            get filteredArtifacts(): Artifact[] {
                let filtered = this.artifacts;

                if (this.search.trim()) {
                    const query = this.search.toLowerCase().trim();
                    filtered = filtered.filter((a: Artifact) =>
                        this.getArtifactName(a).toLowerCase().includes(query) ||
                        this.getArtifactComponent(a).toLowerCase().includes(query) ||
                        this.getArtifactFormat(a).toLowerCase().includes(query)
                    );
                }

                if (this.typeFilter) {
                    filtered = filtered.filter((a: Artifact) => {
                        const type = this.getArtifactType(a).toLowerCase();
                        return type === this.typeFilter;
                    });
                }

                if (this.componentFilter) {
                    filtered = filtered.filter((a: Artifact) =>
                        this.getArtifactComponent(a) === this.componentFilter
                    );
                }

                return filtered;
            },

            get totalPages(): number {
                return Math.ceil(this.filteredArtifacts.length / this.pageSize);
            },

            get paginatedArtifacts(): Artifact[] {
                const start = (this.currentPage - 1) * this.pageSize;
                const end = start + this.pageSize;
                return this.filteredArtifacts.slice(start, end);
            },

            get totalItems(): number {
                return this.filteredArtifacts.length;
            },

            // Computed-like getters for available artifacts modal
            get availableUniqueComponents(): string[] {
                const components = new Set<string>();
                this.availableArtifacts.forEach((a: AvailableArtifact) => {
                    if (a.component?.name) components.add(a.component.name);
                });
                return Array.from(components).sort();
            },

            get filteredAvailableArtifacts(): AvailableArtifact[] {
                let filtered = this.availableArtifacts;

                if (this.availableSearch.trim()) {
                    const query = this.availableSearch.toLowerCase().trim();
                    filtered = filtered.filter((a: AvailableArtifact) =>
                        a.name.toLowerCase().includes(query) ||
                        (a.component?.name || '').toLowerCase().includes(query) ||
                        this.getAvailableArtifactFormat(a).toLowerCase().includes(query)
                    );
                }

                if (this.availableTypeFilter) {
                    filtered = filtered.filter((a: AvailableArtifact) => a.artifact_type === this.availableTypeFilter);
                }

                if (this.availableComponentFilter) {
                    filtered = filtered.filter((a: AvailableArtifact) =>
                        a.component?.name === this.availableComponentFilter
                    );
                }

                return filtered;
            },

            get allFilteredSelected(): boolean {
                return this.filteredAvailableArtifacts.length > 0 &&
                    this.filteredAvailableArtifacts.every((a: AvailableArtifact) => this.selectedArtifacts.has(a.id));
            },

            // Artifact data extraction methods
            getArtifactType(artifact: Artifact): string {
                if (artifact.sbom || artifact.artifact_type === 'sbom') return 'sbom';
                if (artifact.document || artifact.artifact_type === 'document') return 'document';
                return artifact.type || 'unknown';
            },

            getArtifactName(artifact: Artifact): string {
                if (artifact.sbom) return artifact.sbom.name;
                if (artifact.document) return artifact.document.name;
                return artifact.artifact_name || artifact.name || 'Unknown';
            },

            getArtifactDate(artifact: Artifact): string {
                let dateStr: string | undefined;
                if (artifact.sbom) dateStr = artifact.sbom.created_at;
                else if (artifact.document) dateStr = artifact.document.created_at;
                else dateStr = artifact.created_at;
                return this.formatDate(dateStr);
            },

            getArtifactComponent(artifact: Artifact): string {
                if (artifact.sbom?.component) return artifact.sbom.component.name;
                if (artifact.document?.component) return artifact.document.component.name;
                return artifact.component_name || '-';
            },

            getArtifactFormat(artifact: Artifact): string {
                if (artifact.sbom) {
                    const format = artifact.sbom.format || 'unknown';
                    const formatDisplay = format === 'cyclonedx' ? 'CycloneDX' : format.toUpperCase();
                    return `${formatDisplay} ${artifact.sbom.format_version || ''}`.trim();
                }
                if (artifact.document) {
                    const type = artifact.document.document_type || 'unknown';
                    return type.charAt(0).toUpperCase() + type.slice(1);
                }
                if (artifact.artifact_type === 'sbom' && artifact.sbom_format) {
                    const formatDisplay = artifact.sbom_format === 'cyclonedx' ? 'CycloneDX' : artifact.sbom_format.toUpperCase();
                    return `${formatDisplay} ${artifact.sbom_format_version || ''}`.trim();
                }
                if (artifact.artifact_type === 'document' && artifact.document_type) {
                    return artifact.document_type.charAt(0).toUpperCase() + artifact.document_type.slice(1);
                }
                return 'Unknown';
            },

            getArtifactVersion(artifact: Artifact): string | null {
                if (artifact.sbom) return artifact.sbom.version || null;
                if (artifact.document) return artifact.document.version || null;
                return artifact.sbom_version || artifact.document_version || null;
            },

            getArtifactUrl(artifact: Artifact): string {
                const isPublicView = window.location.pathname.includes('/public/');
                if (artifact.sbom) {
                    const sbomId = artifact.sbom.id;
                    const componentId = artifact.sbom.component?.id;
                    if (!sbomId || !componentId) return '#';
                    return isPublicView ? `/public/component/${componentId}/sbom/${sbomId}/` : `/component/${componentId}/sbom/${sbomId}/`;
                }
                if (artifact.document) {
                    const documentId = artifact.document.id;
                    const componentId = artifact.document.component?.id;
                    if (!documentId || !componentId) return '#';
                    return isPublicView ? `/public/component/${componentId}/document/${documentId}/` : `/component/${componentId}/document/${documentId}/`;
                }
                // Handle flat API response
                if (artifact.artifact_type === 'sbom' && artifact.sbom_id && artifact.component_id) {
                    return isPublicView ? `/public/component/${artifact.component_id}/sbom/${artifact.sbom_id}/` : `/component/${artifact.component_id}/sbom/${artifact.sbom_id}/`;
                }
                if (artifact.artifact_type === 'document' && artifact.document_id && artifact.component_id) {
                    return isPublicView ? `/public/component/${artifact.component_id}/document/${artifact.document_id}/` : `/component/${artifact.component_id}/document/${artifact.document_id}/`;
                }
                return '#';
            },

            getComponentUrl(artifact: Artifact): string {
                const isPublicView = window.location.pathname.includes('/public/');
                let componentId: string | undefined;
                if (artifact.sbom?.component) componentId = artifact.sbom.component.id;
                else if (artifact.document?.component) componentId = artifact.document.component.id;
                else componentId = artifact.component_id;
                if (!componentId) return '#';
                return isPublicView ? `/public/component/${componentId}/` : `/component/${componentId}/`;
            },

            getTypeIcon(type?: string): string {
                if (!type) return 'fas fa-file';
                switch (type.toLowerCase()) {
                    case 'sbom':
                        return 'fas fa-file-code';
                    case 'document':
                        return 'fas fa-file-alt';
                    default:
                        return 'fas fa-file';
                }
            },

            getArtifactIconClass(artifact: Artifact): string {
                const type = this.getArtifactType(artifact);
                if (type === 'sbom') return 'sbom-icon';
                if (type === 'document') return 'document-icon';
                return 'default-icon';
            },

            getArtifactBadgeClass(artifact: Artifact): string {
                const type = this.getArtifactType(artifact);
                if (type === 'sbom') return 'badge bg-success-subtle text-success';
                if (type === 'document') return 'badge bg-warning-subtle text-warning';
                return 'badge bg-secondary-subtle text-secondary';
            },

            // Available artifact methods
            getAvailableTypeIcon(artifact: AvailableArtifact): string {
                if (artifact.artifact_type === 'sbom') return 'fas fa-file-code';
                if (artifact.artifact_type === 'document') return 'fas fa-file-alt';
                return 'fas fa-file';
            },

            getAvailableArtifactIconClass(artifact: AvailableArtifact): string {
                if (artifact.artifact_type === 'sbom') return 'sbom-icon';
                if (artifact.artifact_type === 'document') return 'document-icon';
                return 'default-icon';
            },

            getAvailableArtifactFormat(artifact: AvailableArtifact): string {
                if (artifact.artifact_type === 'sbom' && artifact.format && artifact.format_version) {
                    const formatDisplay = artifact.format === 'cyclonedx' ? 'CycloneDX' : artifact.format.toUpperCase();
                    return `${formatDisplay} ${artifact.format_version}`;
                }
                if (artifact.artifact_type === 'document' && artifact.document_type) {
                    return artifact.document_type.charAt(0).toUpperCase() + artifact.document_type.slice(1);
                }
                return 'Unknown';
            },

            // Utility methods
            formatDate(dateString?: string): string {
                if (!dateString) return '-';
                const date = new Date(dateString);
                return date.toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric'
                });
            },

            truncateText(text: string, maxLength: number): string {
                if (!text || text.length <= maxLength) return text || '';
                return text.substring(0, maxLength - 3) + '...';
            },

            formatFileSize(bytes?: number): string {
                if (!bytes) return '-';
                const units = ['B', 'KB', 'MB', 'GB'];
                let size = bytes;
                let unitIndex = 0;
                while (size >= 1024 && unitIndex < units.length - 1) {
                    size /= 1024;
                    unitIndex++;
                }
                return `${size.toFixed(1)} ${units[unitIndex]}`;
            },

            // Filter handlers
            handleSearch() {
                this.currentPage = 1;
            },

            handleTypeFilter() {
                this.currentPage = 1;
            },

            handleComponentFilter() {
                this.currentPage = 1;
            },

            clearAvailableFilters() {
                this.availableSearch = '';
                this.availableTypeFilter = '';
                this.availableComponentFilter = '';
            },

            // Modal methods
            openAddModal() {
                this.loadAvailableArtifacts();
                this.selectedArtifacts = new Set();
                this.availableSearch = '';
                this.availableTypeFilter = '';
                this.availableComponentFilter = '';
                this.showAddModal = true;
            },

            closeAddModal() {
                this.showAddModal = false;
                this.selectedArtifacts = new Set();
            },

            // Selection methods
            toggleArtifactSelection(artifactId: string) {
                if (this.selectedArtifacts.has(artifactId)) {
                    this.selectedArtifacts.delete(artifactId);
                } else {
                    this.selectedArtifacts.add(artifactId);
                }
                // Force reactivity
                this.selectedArtifacts = new Set(this.selectedArtifacts);
            },

            isSelected(artifactId: string): boolean {
                return this.selectedArtifacts.has(artifactId);
            },

            selectAllFiltered() {
                this.filteredAvailableArtifacts.forEach((a: AvailableArtifact) => {
                    this.selectedArtifacts.add(a.id);
                });
                this.selectedArtifacts = new Set(this.selectedArtifacts);
            },

            clearSelection() {
                this.selectedArtifacts = new Set();
            },

            toggleAllFiltered(event: Event) {
                const isChecked = (event.target as HTMLInputElement).checked;
                if (isChecked) {
                    this.selectAllFiltered();
                } else {
                    const filteredIds = new Set(this.filteredAvailableArtifacts.map((a: AvailableArtifact) => a.id));
                    this.selectedArtifacts = new Set(
                        Array.from(this.selectedArtifacts).filter(id => !filteredIds.has(id))
                    );
                }
            },

            // CRUD methods
            async addSelectedArtifacts() {
                if (this.selectedArtifacts.size === 0) return;

                this.isSubmitting = true;
                try {
                    const artifactIds = Array.from(this.selectedArtifacts);
                    let addedCount = 0;
                    const errors: string[] = [];

                    for (const artifactId of artifactIds) {
                        const artifact = this.availableArtifacts.find((a: AvailableArtifact) => a.id === artifactId);
                        if (!artifact) continue;

                        try {
                            let payload: { sbom_id: string } | { document_id: string };
                            if (artifact.artifact_type === 'sbom') {
                                payload = { sbom_id: artifactId };
                            } else if (artifact.artifact_type === 'document') {
                                payload = { document_id: artifactId };
                            } else {
                                errors.push(`${artifact.name}: Unknown artifact type`);
                                continue;
                            }
                            await $axios.post(`/api/v1/releases/${this.releaseId}/artifacts`, payload);
                            addedCount++;
                        } catch (err: unknown) {
                            const axiosErr = err as { response?: { data?: { detail?: string } } };
                            errors.push(`${artifact.name}: ${axiosErr.response?.data?.detail || 'Failed'}`);
                        }
                    }

                    if (addedCount > 0) {
                        showSuccess(`${addedCount} artifact(s) added to release`);
                    }
                    if (errors.length > 0) {
                        showError(`Failed to add some artifacts:\n${errors.join('\n')}`);
                    }

                    this.closeAddModal();
                    await this.loadArtifacts();
                } catch (error) {
                    console.error('Failed to add artifacts:', error);
                    showError('Failed to add artifacts');
                } finally {
                    this.isSubmitting = false;
                }
            },

            async removeArtifact(artifact: Artifact) {
                const confirmed = await confirmDelete({
                    itemName: this.getArtifactName(artifact),
                    itemType: 'artifact from release'
                });

                if (!confirmed) return;

                try {
                    await $axios.delete(`/api/v1/releases/${this.releaseId}/artifacts/${artifact.id}`);
                    showSuccess('Artifact removed from release');
                    await this.loadArtifacts();
                } catch (error) {
                    console.error('Failed to remove artifact:', error);
                    showError('Failed to remove artifact');
                }
            }
        };
    });
}

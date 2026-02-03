import Alpine from 'alpinejs';
import $axios from '../utils';
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

function formatSbomDisplay(format?: string, version?: string): string {
    const normalizedFormat = format || 'unknown';
    const formatDisplay = normalizedFormat === 'cyclonedx' ? 'CycloneDX' : normalizedFormat.toUpperCase();
    return `${formatDisplay} ${version || ''}`.trim();
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
            showDeleteModal: false,
            deleteTarget: null as Artifact | null,
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

            // Modal sorting
            availableSortColumn: 'name' as string,
            availableSortDirection: 'asc' as 'asc' | 'desc',

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

                // Apply sorting
                const sortColumn = this.availableSortColumn;
                const sortDir = this.availableSortDirection === 'asc' ? 1 : -1;

                filtered = [...filtered].sort((a: AvailableArtifact, b: AvailableArtifact) => {
                    let aVal: string | number = '';
                    let bVal: string | number = '';

                    switch (sortColumn) {
                        case 'type':
                            aVal = a.artifact_type || '';
                            bVal = b.artifact_type || '';
                            break;
                        case 'name':
                            aVal = a.name.toLowerCase();
                            bVal = b.name.toLowerCase();
                            break;
                        case 'component':
                            aVal = (a.component?.name || '').toLowerCase();
                            bVal = (b.component?.name || '').toLowerCase();
                            break;
                        case 'format':
                            aVal = this.getAvailableArtifactFormat(a).toLowerCase();
                            bVal = this.getAvailableArtifactFormat(b).toLowerCase();
                            break;
                        case 'version':
                            aVal = (a.version || '').toLowerCase();
                            bVal = (b.version || '').toLowerCase();
                            break;
                        case 'created':
                            aVal = a.created_at ? new Date(a.created_at).getTime() : 0;
                            bVal = b.created_at ? new Date(b.created_at).getTime() : 0;
                            break;
                        default:
                            aVal = a.name.toLowerCase();
                            bVal = b.name.toLowerCase();
                    }

                    if (aVal < bVal) return -1 * sortDir;
                    if (aVal > bVal) return 1 * sortDir;
                    return 0;
                });

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
                    return formatSbomDisplay(artifact.sbom.format, artifact.sbom.format_version);
                }
                if (artifact.document) {
                    const type = artifact.document.document_type || 'unknown';
                    return type.charAt(0).toUpperCase() + type.slice(1);
                }
                if (artifact.artifact_type === 'sbom' && artifact.sbom_format) {
                    return formatSbomDisplay(artifact.sbom_format, artifact.sbom_format_version);
                }
                if (artifact.artifact_type === 'document' && artifact.document_type) {
                    return artifact.document_type.charAt(0).toUpperCase() + artifact.document_type.slice(1);
                }
                return 'Unknown';
            },

            getArtifactFormatClass(artifact: Artifact): string {
                const isSbom = artifact.sbom || artifact.artifact_type === 'sbom';
                if (isSbom) {
                    const format = artifact.sbom?.format || artifact.sbom_format || '';
                    const isCycloneDX = format.toLowerCase().includes('cyclonedx');
                    return `tw-sbom-format ${isCycloneDX ? 'tw-sbom-format-cyclonedx' : 'tw-sbom-format-spdx'}`;
                }
                return 'text-text-muted';
            },

            isArtifactTypeSbom(artifact: Artifact): boolean {
                return !!(artifact.sbom || artifact.artifact_type === 'sbom');
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
                    return isPublicView ? `/public/components/${componentId}/sboms/${sbomId}/` : `/components/${componentId}/sboms/${sbomId}/`;
                }
                if (artifact.document) {
                    const documentId = artifact.document.id;
                    const componentId = artifact.document.component?.id;
                    if (!documentId || !componentId) return '#';
                    return isPublicView ? `/public/component/${componentId}/document/${documentId}/` : `/component/${componentId}/document/${documentId}/`;
                }
                // Handle flat API response
                if (artifact.artifact_type === 'sbom' && artifact.sbom_id && artifact.component_id) {
                    return isPublicView ? `/public/components/${artifact.component_id}/sboms/${artifact.sbom_id}/` : `/components/${artifact.component_id}/sboms/${artifact.sbom_id}/`;
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
                if (type === 'sbom') return 'bg-success/10 text-success';
                if (type === 'document') return 'bg-warning/10 text-warning';
                return 'bg-surface text-text-muted';
            },

            getArtifactBadgeClass(artifact: Artifact): string {
                const type = this.getArtifactType(artifact);
                if (type === 'sbom') return 'bg-success/10 text-success border border-success/30';
                if (type === 'document') return 'bg-warning/10 text-warning border border-warning/30';
                return 'bg-surface text-text-muted border border-border';
            },

            // Available artifact methods
            getAvailableTypeIcon(artifact: AvailableArtifact): string {
                if (artifact.artifact_type === 'sbom') return 'fas fa-file-code';
                if (artifact.artifact_type === 'document') return 'fas fa-file-alt';
                return 'fas fa-file';
            },

            getAvailableArtifactIconClass(artifact: AvailableArtifact): string {
                if (artifact.artifact_type === 'sbom') return 'bg-success/10 text-success';
                if (artifact.artifact_type === 'document') return 'bg-warning/10 text-warning';
                return 'bg-surface text-text-muted';
            },

            getAvailableArtifactFormat(artifact: AvailableArtifact): string {
                if (artifact.artifact_type === 'sbom' && artifact.format) {
                    return formatSbomDisplay(artifact.format, artifact.format_version);
                }
                if (artifact.artifact_type === 'document' && artifact.document_type) {
                    return artifact.document_type.charAt(0).toUpperCase() + artifact.document_type.slice(1);
                }
                return 'Unknown';
            },

            getAvailableArtifactFormatClass(artifact: AvailableArtifact): string {
                if (artifact.artifact_type === 'sbom' && artifact.format) {
                    const isCycloneDX = artifact.format.toLowerCase().includes('cyclonedx');
                    return `tw-sbom-format ${isCycloneDX ? 'tw-sbom-format-cyclonedx' : 'tw-sbom-format-spdx'}`;
                }
                return 'text-text-muted';
            },

            isArtifactSbom(artifact: AvailableArtifact): boolean {
                return artifact.artifact_type === 'sbom';
            },

            getAvailableArtifactUrl(artifact: AvailableArtifact): string {
                const componentId = artifact.component?.id;
                if (!componentId) return '#';

                if (artifact.artifact_type === 'sbom') {
                    return `/components/${componentId}/sboms/${artifact.id}/`;
                }
                if (artifact.artifact_type === 'document') {
                    return `/component/${componentId}/document/${artifact.id}/`;
                }
                return '#';
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

            setAvailableSort(column: string) {
                if (this.availableSortColumn === column) {
                    // Toggle direction if same column
                    this.availableSortDirection = this.availableSortDirection === 'asc' ? 'desc' : 'asc';
                } else {
                    // New column, default to ascending
                    this.availableSortColumn = column;
                    this.availableSortDirection = 'asc';
                }
            },

            // Modal methods
            openAddModal() {
                this.loadAvailableArtifacts();
                this.selectedArtifacts = new Set();
                this.availableSearch = '';
                this.availableSortColumn = 'name';
                this.availableSortDirection = 'asc';
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

            openDeleteModal(artifact: Artifact) {
                this.deleteTarget = artifact;
                this.showDeleteModal = true;
            },

            closeDeleteModal() {
                this.showDeleteModal = false;
                this.deleteTarget = null;
            },

            async confirmRemoveArtifact() {
                if (!this.deleteTarget) return;

                try {
                    await $axios.delete(`/api/v1/releases/${this.releaseId}/artifacts/${this.deleteTarget.id}`);
                    showSuccess('Artifact removed from release');
                    this.closeDeleteModal();
                    await this.loadArtifacts();
                } catch (error) {
                    console.error('Failed to remove artifact:', error);
                    showError('Failed to remove artifact');
                }
            }
        };
    });
}

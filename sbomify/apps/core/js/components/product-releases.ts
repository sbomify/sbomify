import Alpine from 'alpinejs';
import $axios from '../utils';
import { showError, showSuccess } from '../alerts';
import { createPaginationData } from './pagination-controls';

interface Release {
    id: string;
    name: string;
    version?: string;
    description?: string;
    is_prerelease: boolean;
    is_latest: boolean;
    release_date?: string;
    created_at?: string;
    artifact_count?: number;
}

interface ReleaseForm {
    id: string | null;
    name: string;
    version: string;
    description: string;
    is_prerelease: boolean;
    created_at: string;
    released_at: string;
}

interface ProductReleasesParams {
    productId: string;
    initialReleases?: Release[];
    totalCount?: number;
    isPublicView?: boolean;
    canCreate?: boolean;
    canEdit?: boolean;
    canDelete?: boolean;
}

function getDefaultDateTime(): string {
    const now = new Date();
    const pad = (n: number) => n.toString().padStart(2, '0');
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

function formatDateTimeForInput(value?: string): string {
    if (!value) return getDefaultDateTime();
    const date = new Date(value);
    if (isNaN(date.getTime())) return getDefaultDateTime();
    const pad = (n: number) => n.toString().padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function registerProductReleases() {
    Alpine.data('productReleases', ({
        productId,
        initialReleases = [],
        totalCount = 0,
        isPublicView = false,
        canCreate = true,
        canEdit = true,
        canDelete = true
    }: ProductReleasesParams) => {
        const paginationData = createPaginationData(totalCount, [10, 15, 25, 50], 1);
        const defaultDateTime = getDefaultDateTime();

        return {
            releases: initialReleases as Release[],
            isLoading: false,
            showModal: false,
            showDeleteModal: false,
            deleteTarget: null as Release | null,
            productId,
            isPublicView,
            canCreate,
            canEdit,
            canDelete,
            form: {
                id: null,
                name: '',
                version: '',
                description: '',
                is_prerelease: false,
                created_at: defaultDateTime,
                released_at: defaultDateTime
            } as ReleaseForm,
            ...paginationData,

            init() {
                if (initialReleases.length === 0 && totalCount > 0) {
                    this.loadReleases();
                }

                this.$watch('currentPage', () => this.loadReleases());
                this.$watch('pageSize', () => {
                    this.currentPage = 1;
                    this.loadReleases();
                });
            },

            async loadReleases() {
                this.isLoading = true;
                try {
                    const params = new URLSearchParams({
                        product_id: this.productId,
                        page: this.currentPage.toString(),
                        page_size: this.pageSize.toString()
                    });

                    const response = await $axios.get(`/api/v1/releases?${params.toString()}`);
                    // Handle both array format and paginated format
                    if (Array.isArray(response.data)) {
                        this.releases = response.data;
                        this.totalItems = response.data.length;
                    } else {
                        this.releases = response.data.items || response.data.results || [];
                        this.totalItems = response.data.pagination?.total || response.data.count || this.releases.length;
                    }
                } catch (error) {
                    console.error('Failed to load releases:', error);
                    showError('Failed to load releases');
                } finally {
                    this.isLoading = false;
                }
            },

            openCreateModal() {
                const now = getDefaultDateTime();
                this.form = {
                    id: null,
                    name: '',
                    version: '',
                    description: '',
                    is_prerelease: false,
                    created_at: now,
                    released_at: now
                };
                this.showModal = true;
            },

            openEditModal(release: Release) {
                this.form = {
                    id: release.id,
                    name: release.name,
                    version: release.version || '',
                    description: release.description || '',
                    is_prerelease: release.is_prerelease,
                    created_at: formatDateTimeForInput(release.created_at),
                    released_at: formatDateTimeForInput(release.release_date || release.created_at)
                };
                this.showModal = true;
            },

            closeModal() {
                this.showModal = false;
                const now = getDefaultDateTime();
                this.form = {
                    id: null,
                    name: '',
                    version: '',
                    description: '',
                    is_prerelease: false,
                    created_at: now,
                    released_at: now
                };
            },

            async submitRelease() {
                if (!this.form.name || !this.form.name.trim()) {
                    showError('Release name is required');
                    return;
                }

                try {
                    const createdAt = this.form.created_at ? new Date(this.form.created_at).toISOString() : null;
                    const releasedAt = this.form.released_at ? new Date(this.form.released_at).toISOString() : null;

                    if (this.form.id) {
                        const data: Record<string, unknown> = {
                            name: this.form.name.trim(),
                            description: this.form.description?.trim() || null,
                            is_prerelease: this.form.is_prerelease
                        };
                        if (this.form.version?.trim()) data.version = this.form.version.trim();
                        if (createdAt) data.created_at = createdAt;
                        if (releasedAt) data.released_at = releasedAt;

                        await $axios.patch(`/api/v1/releases/${this.form.id}`, data);
                        showSuccess('Release updated successfully');
                    } else {
                        const data: Record<string, unknown> = {
                            name: this.form.name.trim(),
                            description: this.form.description?.trim() || null,
                            is_prerelease: this.form.is_prerelease,
                            product_id: this.productId
                        };
                        if (this.form.version?.trim()) data.version = this.form.version.trim();
                        if (createdAt) data.created_at = createdAt;
                        if (releasedAt) data.released_at = releasedAt;

                        await $axios.post('/api/v1/releases', data);
                        showSuccess('Release created successfully');
                    }

                    this.closeModal();
                    await this.loadReleases();
                } catch (error: unknown) {
                    console.error('Failed to save release:', error);
                    const axiosError = error as { response?: { data?: { detail?: string } } };
                    const detail = axiosError?.response?.data?.detail;
                    showError(detail || 'Failed to save release');
                }
            },

            openDeleteModal(release: Release) {
                this.deleteTarget = release;
                this.showDeleteModal = true;
            },

            closeDeleteModal() {
                this.showDeleteModal = false;
                this.deleteTarget = null;
            },

            async confirmDeleteRelease() {
                if (!this.deleteTarget) return;

                try {
                    await $axios.delete(`/api/v1/releases/${this.deleteTarget.id}`);
                    showSuccess('Release deleted successfully');
                    this.closeDeleteModal();
                    await this.loadReleases();
                } catch (error) {
                    console.error('Failed to delete release:', error);
                    showError('Failed to delete release');
                }
            },

            getReleaseUrl(release: Release): string {
                if (this.isPublicView) {
                    return `/public/product/${this.productId}/release/${release.id}/`;
                }
                return `/product/${this.productId}/release/${release.id}/`;
            },

            formatDate(dateString?: string): string {
                if (!dateString) return '-';
                const date = new Date(dateString);
                return date.toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric'
                });
            }
        };
    });
}

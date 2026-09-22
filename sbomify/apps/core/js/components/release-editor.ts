import Alpine from 'alpinejs';
import $axios from '../utils';
import { showError, showSuccess } from '../alerts';

interface Release {
    id: string;
    name: string;
    version?: string;
    description?: string;
    is_prerelease: boolean;
    is_latest: boolean;
    release_date?: string;
    created_at?: string;
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

interface ReleaseEditorParams {
    initialReleases?: Release[];
    refreshEvent: string;
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

// The server owns the table. This controller only edits its supplied records
// through the existing API, then asks the owning HTMX frame to refresh.
export function registerReleaseEditor() {
    Alpine.data('releaseEditor', ({ initialReleases = [], refreshEvent, canDelete = false }: ReleaseEditorParams) => ({
        releases: initialReleases,
        canDelete,
        saving: false,
        showModal: false,
        showDeleteModal: false,
        deleteTarget: null as Release | null,
        form: {
            id: null, name: '', version: '', description: '', is_prerelease: false,
            created_at: '', released_at: ''
        } as ReleaseForm,

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
            // Dispatch event to close any open datetime pickers
            window.dispatchEvent(new CustomEvent('close-all-pickers'));
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
            if (this.saving || !this.form.id) return;
            if (!this.form.name || !this.form.name.trim()) {
                showError('Release name is required');
                return;
            }

            this.saving = true;
            try {
                const createdAt = this.form.created_at ? new Date(this.form.created_at).toISOString() : null;
                const releasedAt = this.form.released_at ? new Date(this.form.released_at).toISOString() : null;

                const data: Record<string, unknown> = {
                    name: this.form.name.trim(),
                    description: this.form.description?.trim() || null,
                    version: this.form.version.trim(),
                    is_prerelease: this.form.is_prerelease
                };
                if (createdAt) data.created_at = createdAt;
                if (releasedAt) data.released_at = releasedAt;

                await $axios.patch(`/api/v1/releases/${this.form.id}`, data);
                showSuccess('Release updated');

                this.closeModal();
                this.$dispatch(refreshEvent);
            } catch (error: unknown) {
                console.error('Failed to save release:', error);
                const axiosError = error as { response?: { data?: { detail?: string } } };
                const detail = axiosError?.response?.data?.detail;
                showError(detail || 'Failed to save release');
            } finally {
                this.saving = false;
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
            if (!this.deleteTarget || this.saving) return;
            this.saving = true;

            try {
                await $axios.delete(`/api/v1/releases/${this.deleteTarget.id}`);
                showSuccess('Release deleted');
                this.closeDeleteModal();
                this.$dispatch(refreshEvent);
            } catch (error) {
                console.error('Failed to delete release:', error);
                showError('Failed to delete release');
            } finally {
                this.saving = false;
            }
        },

    }));
}

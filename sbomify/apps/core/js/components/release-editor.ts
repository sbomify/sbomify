import Alpine from 'alpinejs';
import { getCsrfToken } from '../csrf';
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
    replaces: string;
    replaces_line: '' | 'same' | 'new';
}

interface ReplaceOption {
    id: string;
    name: string;
}

interface ReplacedRelease extends ReplaceOption {
    drop_in: boolean;
}

interface ReplaceData {
    options: ReplaceOption[];
    replaces: Record<string, ReplacedRelease[]>;
}

interface ReleaseEditorParams {
    initialReleases?: Release[];
    replaceData?: ReplaceData;
    refreshEvent: string;
    canDelete?: boolean;
}

function emptyForm(now = ''): ReleaseForm {
    return {
        id: null, name: '', version: '', description: '', is_prerelease: false,
        created_at: now, released_at: now, replaces: '', replaces_line: ''
    };
}

// A datetime-local value in local time; a missing or invalid value means now.
function formatDateTimeForInput(value?: string): string {
    let date = value ? new Date(value) : new Date();
    if (isNaN(date.getTime())) date = new Date();
    const pad = (n: number) => n.toString().padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// The server owns the table. This controller only edits its supplied records
// through the existing API, then asks the owning HTMX frame to refresh.
export function registerReleaseEditor() {
    Alpine.data('releaseEditor', ({
        initialReleases = [], replaceData = { options: [], replaces: {} }, refreshEvent, canDelete = false
    }: ReleaseEditorParams) => ({
        releases: initialReleases,
        replaceData,
        canDelete,
        saving: false,
        showModal: false,
        showDeleteModal: false,
        deleteTarget: null as Release | null,
        form: emptyForm(),
        // The release date as the dialog opened. The field keeps minutes only,
        // so sending back a date nobody touched would still move it.
        openedReleasedAt: '',
        // What the release replaced as the dialog opened, so an edit that leaves
        // it alone writes no link. A release replacing several is changed on its
        // own page: one select cannot show them.
        openedReplaces: '',
        openedLine: '',
        replacesLocked: false,

        replacedBy(): ReplacedRelease[] {
            return this.replaceData.replaces[this.form.id ?? ''] ?? [];
        },

        // A release it replaces on the same line is no longer monitored, so it
        // is not among the offered options: add it back.
        replaceOptions(): ReplaceOption[] {
            const seen = new Set<string>([this.form.id ?? '']);
            const options: ReplaceOption[] = [];
            for (const option of [...this.replacedBy(), ...this.replaceData.options]) {
                if (seen.has(option.id)) continue;
                seen.add(option.id);
                options.push({ id: option.id, name: option.name });
            }
            return options;
        },

        replacesSummary(): string {
            const names = this.replacedBy().map(release => release.name).join(', ');
            return `${names}. Change these on the release's page.`;
        },

        openEditModal(release: Release) {
            this.form = {
                id: release.id,
                name: release.name,
                version: release.version || '',
                description: release.description || '',
                is_prerelease: release.is_prerelease,
                created_at: formatDateTimeForInput(release.created_at),
                released_at: formatDateTimeForInput(release.release_date || release.created_at),
                replaces: '',
                replaces_line: ''
            };
            const replaced = this.replacedBy();
            this.replacesLocked = replaced.length > 1;
            if (replaced.length === 1) {
                this.form.replaces = replaced[0]!.id;
                this.form.replaces_line = replaced[0]!.drop_in ? 'same' : 'new';
            }
            this.openedReplaces = this.form.replaces;
            this.openedLine = this.form.replaces_line;
            this.openedReleasedAt = this.form.released_at;
            this.showModal = true;
        },

        closeModal() {
            this.showModal = false;
            // Dispatch event to close any open datetime pickers
            window.dispatchEvent(new CustomEvent('close-all-pickers'));
            this.form = emptyForm(formatDateTimeForInput());
            this.replacesLocked = false;
        },

        async submitRelease() {
            if (this.saving || !this.form.id) return;
            if (!this.form.name || !this.form.name.trim()) {
                showError('Release name is required');
                return;
            }
            const replacesChanged = !this.replacesLocked
                && (this.form.replaces !== this.openedReplaces || this.form.replaces_line !== this.openedLine);
            // Same line retires the release it replaces, so the dialog never guesses which line is meant.
            if (replacesChanged && this.form.replaces && !this.form.replaces_line) {
                showError('Choose Same line or New line, or set Release it replaces to None.');
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
                if (releasedAt && this.form.released_at !== this.openedReleasedAt) data.released_at = releasedAt;
                if (replacesChanged) {
                    data.supersedes = this.form.replaces
                        ? [{ release_id: this.form.replaces, drop_in: this.form.replaces_line === 'same' }]
                        : [];
                }

                const response = await fetch(`/api/v1/releases/${this.form.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                    body: JSON.stringify(data),
                });
                if (!response.ok) {
                    const body = await response.json().catch(() => ({}));
                    showError(body.detail || 'Failed to save release');
                    return;
                }
                showSuccess('Release updated');

                this.closeModal();
                this.$dispatch(refreshEvent);
            } catch (error: unknown) {
                console.error('Failed to save release:', error);
                showError('Failed to save release');
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
                const response = await fetch(`/api/v1/releases/${this.deleteTarget.id}`, {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': getCsrfToken() },
                });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
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

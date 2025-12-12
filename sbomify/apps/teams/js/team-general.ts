import Alpine from 'alpinejs';

/**
 * Registers the Alpine.js 'teamGeneral' component for managing general workspace settings.
 * Handles the workspace name editing with unsaved changes tracking.
 */
export function registerTeamGeneral() {
    Alpine.data('teamGeneral', (initialName: string) => ({
        originalName: initialName,
        localName: initialName,

        hasUnsavedChanges(): boolean {
            return this.localName !== this.originalName;
        },
    }));
}


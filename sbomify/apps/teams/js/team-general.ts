import Alpine from 'alpinejs';

/**
 * Registers the Alpine.js 'teamGeneral' component for managing general workspace settings.
 * Handles the workspace name and SBOM freshness window with unsaved changes tracking.
 */
export function registerTeamGeneral() {
    Alpine.data('teamGeneral', (initialName: string, initialFreshness = '') => ({
        originalName: initialName,
        localName: initialName,
        // Held as a string so an emptied field compares equal to an unset one.
        // '' means no freshness policy and '0' is a real window that expires
        // immediately, so the two must not collapse into each other.
        originalFreshness: initialFreshness,
        localFreshness: initialFreshness,

        hasUnsavedChanges(): boolean {
            return this.localName !== this.originalName || this.localFreshness !== this.originalFreshness;
        },
    }));
}


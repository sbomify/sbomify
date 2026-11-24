import Alpine from 'alpinejs';

/**
 * Registers 'dirtySettingsForm', the one save convention the settings forms share.
 *
 * Every card on General saves the same way: the pair stays disabled until
 * something changes, Discard puts the fields back, and leaving the page without
 * saving costs nothing because nothing was taken. Three forms with three
 * conventions on one tab taught the reader to check each one.
 *
 * Values are held as strings so an emptied field compares equal to an unset
 * one: '' means no policy and '0' is a real window that expires immediately,
 * and the two must not collapse into each other.
 */
export function registerTeamGeneral() {
    Alpine.data('dirtySettingsForm', (initial: Record<string, string> = {}) => ({
        original: { ...initial },
        fields: { ...initial },

        hasUnsavedChanges(): boolean {
            return Object.keys(this.original).some((key) => this.fields[key] !== this.original[key]);
        },

        discard(): void {
            this.fields = { ...this.original };
        },
    }));
}

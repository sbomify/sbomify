import Alpine from 'alpinejs';

/**
 * Which assessment cards the reader has open, held outside the DOM.
 *
 * The artifact page refreshes its whole content region when a scan finishes,
 * and a morph re-renders each run card from markup that always says closed. A
 * card whose open state lived in its own `x-data` would therefore shut itself
 * every time an assessment completed, taking the findings the reader had open
 * with it. A store is not part of the swapped DOM, so it survives.
 *
 * Keyed by run id rather than plugin name: a plugin can have more than one run
 * on a page, and they open independently.
 */
interface OpenAssessments {
    ids: string[];
    isOpen(runId: string): boolean;
    toggle(runId: string): void;
}

export function registerOpenAssessmentsStore(): void {
    const store: OpenAssessments = {
        // A plain array rather than a Set: Alpine tracks array assignment, and
        // a Set's add/delete would not re-render the cards reading this.
        ids: [],

        isOpen(runId: string): boolean {
            return this.ids.includes(runId);
        },

        toggle(runId: string): void {
            this.ids = this.isOpen(runId) ? this.ids.filter((id) => id !== runId) : [...this.ids, runId];
        },
    };

    Alpine.store('openAssessments', store);
}

export default { registerOpenAssessmentsStore };

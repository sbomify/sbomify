import Alpine from 'alpinejs';

interface StandardCardParams {
    storageKey: string;
    defaultExpanded: boolean;
}

interface StandardCardData {
    isExpanded: boolean;
    storageKey: string;
    toggleCollapse: () => void;
}

export function registerStandardCard(): void {
    Alpine.data('standardCard', ({ storageKey, defaultExpanded }: StandardCardParams): StandardCardData => {
        return {
            // Use $persist with sessionStorage for card collapse state
            // The persist plugin automatically handles storage key and serialization
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            isExpanded: (Alpine as any).$persist(defaultExpanded)
                .as(`card-collapse-${storageKey}`)
                .using(sessionStorage),
            storageKey,

            toggleCollapse() {
                this.isExpanded = !this.isExpanded;
                // No manual sessionStorage needed - $persist handles it automatically
            }
        };
    });
}

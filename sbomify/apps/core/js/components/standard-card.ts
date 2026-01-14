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

export function registerStandardCard() {
    Alpine.data('standardCard', ({ storageKey, defaultExpanded }: StandardCardParams): StandardCardData => {
        const getInitialExpandedState = (): boolean => {
            if (storageKey) {
                const stored = sessionStorage.getItem(`card-collapse-${storageKey}`);
                if (stored !== null) {
                    return stored === 'true';
                }
            }
            return defaultExpanded;
        };

        return {
            isExpanded: getInitialExpandedState(),
            storageKey,

            toggleCollapse() {
                this.isExpanded = !this.isExpanded;
                if (this.storageKey) {
                    sessionStorage.setItem(`card-collapse-${this.storageKey}`, this.isExpanded.toString());
                }
            }
        };
    });
}

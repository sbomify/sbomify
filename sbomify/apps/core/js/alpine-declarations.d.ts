declare module '@alpinejs/morph' {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const morph: any;
    export default morph;
}

declare module '@alpinejs/mask' {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const mask: any;
    export default mask;
}

declare module '@alpinejs/persist' {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const persist: any;
    export default persist;
}

declare module '@alpinejs/focus' {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const focus: any;
    export default focus;
}

declare module '@alpinejs/intersect' {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const intersect: any;
    export default intersect;
}

declare module '@alpinejs/collapse' {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const collapse: any;
    export default collapse;
}

declare module '@alpinejs/anchor' {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const anchor: any;
    export default anchor;
}

/**
 * Alpine.js Magic Properties
 * Extends Alpine component types with magic properties
 */
declare global {
    namespace Alpine {
        interface ComponentProperties {
            $el: HTMLElement;
            $refs: { [key: string]: HTMLElement };
            $store: AlpineStores;
            $nextTick: (callback: () => void) => void;
            $watch: (property: string, callback: (newValue: unknown, oldValue?: unknown) => void) => void;
            $dispatch: (event: string, detail?: unknown) => void;
        }
    }

    /**
     * Alpine.js Store Type Definitions
     * Provides TypeScript types for all Alpine stores
     */
    interface AlpineStores {
        sidebar: {
            open: boolean;
            toggle(): void;
            close(): void;
        };
        alerts: {
            showSuccess(message: string): void;
            showError(message: string): void;
            showWarning(message: string): void;
            showInfo(message: string): void;
            showToast(options: {
                title: string;
                message: string;
                type: 'success' | 'error' | 'warning' | 'info';
                timer?: number;
                position?: 'top-end' | 'top' | 'top-start' | 'center' | 'bottom' | 'bottom-end' | 'bottom-start';
            }): void;
            showConfirmation(options: {
                title?: string;
                message: string;
                confirmButtonText?: string;
                cancelButtonText?: string;
                type?: 'success' | 'error' | 'warning' | 'info';
            }): Promise<boolean>;
        };
        clipboard: {
            copy(text: string, successMessage?: string, errorMessage?: string): Promise<void>;
            initButtons(container?: HTMLElement | Document): void;
        };
        modals: {
            triggerElements: Record<string, HTMLElement>;
            observers: Map<string, { intersectionObserver: IntersectionObserver; mutationObserver: MutationObserver }>;
            getFocusableElements(container: HTMLElement): HTMLElement[];
            handleTabKey(event: KeyboardEvent, modalElement: HTMLElement): void;
            handleModalOpen(modalElement: HTMLElement, modalId: string): void;
            handleModalClose(modalId: string): void;
            initModal(modalId: string, overlay: HTMLElement): void;
        };
        charts: {
            initVulnerabilityChart(container: HTMLElement, chartType: string): Promise<void>;
        };
    }
}
